"""Public GitHub releases, isolated OS channels and verified compact installers.

No photograph data or credentials are sent. No downloaded Python/PowerShell is
executed. Only a hash-verified, explicitly named product installer may be run.
Compatible with Python 3.8 / Windows 7 as well as the modern distribution.
"""

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPOSITORY = "babkanomer13-dotcom/colorcorrection"
API = "https://api.github.com/repos/" + REPOSITORY
RELEASES_PAGE = "https://github.com/" + REPOSITORY + "/releases"
MAX_JSON = 2 * 1024**2
MAX_FILE = 2 * 1024**3 - 1
MAX_TOTAL = 6 * 1024**3
MUTEXES = {"win10": "Local\\ColorPro.Desktop", "win7": "Local\\ColorProWin7.Desktop"}


class Cancelled(Exception):
    pass


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError("Неверный номер версии ColorPro")
    return tuple(int(part) for part in value.split("."))


def safe_url(url):
    parsed = urllib.parse.urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname
        in {
            "api.github.com",
            "github.com",
            "release-assets.githubusercontent.com",
            "objects.githubusercontent.com",
        }
        and parsed.port in {None, 443}
        and parsed.username is None
        and parsed.password is None
    )


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not safe_url(newurl):
            raise ValueError("Недоверенный адрес загрузки обновления")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def request(url, headers=None):
    if not safe_url(url):
        raise ValueError("Недоверенный адрес обновления")
    try:
        return urllib.request.build_opener(SafeRedirect()).open(  # noqa: S310 -- HTTPS allowlist above
            urllib.request.Request(  # noqa: S310 -- fixed HTTPS GitHub hosts, including redirects
                url,
                headers={
                    "User-Agent": "ColorPro-Updater",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                    **(headers or {}),
                },
            ),
            timeout=30,
        )
    except urllib.error.HTTPError as error:
        if error.code in {403, 429}:
            raise ValueError("GitHub временно ограничил запросы. Попробуйте позже.") from None
        raise ValueError(f"Сервер обновлений вернул HTTP {error.code}") from None
    except (urllib.error.URLError, OSError):
        raise ValueError(
            "Нет защищённого соединения с GitHub. Проверьте интернет, дату и "
            "сертификаты Windows. Обработка фотографий доступна без интернета."
        ) from None


def read_json(url, asset=None):
    with request(url) as response:
        raw = response.read(MAX_JSON + 1)
    if len(raw) > MAX_JSON:
        raise ValueError("Слишком большой ответ сервера")
    if asset and (len(raw) != asset["size"] or hashlib.sha256(raw).hexdigest() != asset["sha256"]):
        raise ValueError("Описание выпуска повреждено")
    return json.loads(raw)


def asset_info(asset, version):
    prefix = "https://github.com/" + REPOSITORY + "/releases/download/colorpro-v" + version + "/"
    name = asset.get("name", "")
    digest = asset.get("digest", "")
    size = asset.get("size")
    if (
        not re.fullmatch(r"ColorPro-[a-zA-Z0-9.\-]+", name)
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest)
        or type(size) is not int
        or not 0 < size <= MAX_FILE
        or asset.get("browser_download_url") != prefix + name
        or asset.get("state") != "uploaded"
    ):
        raise ValueError("У выпуска нет корректных файлов и контрольных сумм GitHub")
    return dict(name=name, size=size, sha256=digest[7:], url=prefix + name)


def validate_manifest(manifest, assets, version, platform):
    if (
        manifest.get("schema") != "colorpro-update-v1"
        or manifest.get("version") != version
        or manifest.get("platform") != platform
    ):
        raise ValueError("Выпуск не подходит для этой версии Windows")
    prefix = "ColorPro-{}-{}-x64-Setup".format(
        version, {"win10": "Win10", "win7": "Win7"}[platform]
    )
    installer = prefix + ".exe"
    files = manifest.get("files", [])
    if (
        manifest.get("installer") != installer
        or not isinstance(files, list)
        or not 1 <= len(files) <= 8
    ):
        raise ValueError("Неверный комплект установщика")
    names = [row.get("name", "") for row in files]
    if installer not in names or len(set(names)) != len(names):
        raise ValueError("Повторяющиеся файлы или нет установщика")
    verified = []
    for row in files:
        name = row.get("name", "")
        if name != installer and not re.fullmatch(re.escape(prefix) + r"-\d+[a-z]?\.bin", name):
            raise ValueError("Посторонний файл в обновлении")
        asset = assets.get(name)
        if not asset:
            raise ValueError("Публикация неполная: отсутствует " + name)
        info = asset_info(asset, version)
        if row.get("size") != info["size"] or row.get("sha256") != info["sha256"]:
            raise ValueError("Контрольные суммы GitHub и описания выпуска различаются")
        verified.append(info)
    if sum(row["size"] for row in verified) > MAX_TOTAL:
        raise ValueError("Слишком большой комплект обновления")
    kind = manifest.get("kind", "full")
    if kind not in {"compact", "full"}:
        raise ValueError("Неизвестный тип обновления")
    if kind == "compact" and (len(verified) != 1 or verified[0]["size"] > 150 * 1024**2):
        raise ValueError("Неверный компактный пакет обновления")
    return dict(version=version, platform=platform, installer=installer, files=verified, kind=kind)


def latest_release(current_version, platform):
    version_tuple(current_version)
    if platform not in MUTEXES:
        raise ValueError("Обновления устанавливаются только в собранном приложении")
    releases = read_json(API + "/releases?per_page=30")
    if not isinstance(releases, list):
        raise ValueError("Неверный ответ сервера обновлений")
    candidates = []
    for release in releases:
        tag = release.get("tag_name", "")
        if (
            release.get("draft")
            or release.get("prerelease")
            or not re.fullmatch(r"colorpro-v\d+\.\d+\.\d+", tag)
        ):
            continue
        version = tag[len("colorpro-v") :]
        if version_tuple(version) > version_tuple(current_version):
            candidates.append((version_tuple(version), version, release))
    for _, version, release in sorted(candidates, reverse=True):
        assets = {a["name"]: a for a in release.get("assets", [])}
        name = f"ColorPro-{version}-{platform}-update.json"
        if name not in assets:
            continue  # A modern-only release must not update the legacy channel.
        info = asset_info(assets[name], version)
        manifest = read_json(info["url"], info)
        result = validate_manifest(manifest, assets, version, platform)
        result["notes"] = str(release.get("body") or "")[:6000]
        return result
    return None


def download_update(release, cache, progress=lambda done, total: None, cancelled=lambda: False):
    version_tuple(release["version"])
    if release["platform"] not in MUTEXES:
        raise ValueError("Неизвестная платформа")
    folder = Path(cache) / (release["platform"] + "-" + release["version"])
    folder.mkdir(parents=True, exist_ok=True)
    total = sum(row["size"] for row in release["files"])
    if shutil.disk_usage(folder).free < total + 256 * 1024**2:
        raise ValueError("Недостаточно места для загрузки обновления")
    done = 0
    for row in release["files"]:
        if cancelled():
            raise Cancelled()
        destination = folder / row["name"]
        if destination.is_symlink():
            raise ValueError("Недопустимый путь в кэше обновлений")
        destination.resolve().relative_to(folder.resolve())
        if (
            destination.is_file()
            and destination.stat().st_size == row["size"]
            and sha256(destination) == row["sha256"]
        ):
            done += row["size"]
            progress(done, total)
            continue
        partial = destination.with_suffix(destination.suffix + ".part")
        if partial.is_symlink():
            raise ValueError("Недопустимый временный файл")
        offset = partial.stat().st_size if partial.exists() else 0
        if offset >= row["size"]:
            offset = 0
        headers = {"Accept": "application/octet-stream"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        with request(row["url"], headers) as source:
            if source.status == 206:
                expected = f"bytes {offset}-{row['size'] - 1}/{row['size']}"
                if source.headers.get("Content-Range") != expected:
                    raise ValueError("Неверный диапазон загружаемого файла")
            elif source.status == 200:
                offset = 0
            else:
                raise ValueError("Неожиданный ответ при загрузке")
            count = offset
            with partial.open("ab" if offset else "wb") as output:
                while True:
                    if cancelled():
                        raise Cancelled()
                    chunk = source.read(1024**2)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > row["size"]:
                        raise ValueError("Превышен размер файла обновления")
                    output.write(chunk)
                    progress(done + count, total)
        if count != row["size"] or sha256(partial) != row["sha256"]:
            # Only this task-owned partial download is removed; nothing installed.
            partial.unlink()
            raise ValueError("Загрузка повреждена. Повторите загрузку обновления.")
        os.replace(str(partial), str(destination))
        done += count
    return folder


def installer_command(release, folder, install):
    """Verify again immediately before launch. Never invoke a shell."""
    folder, install = Path(folder).resolve(), Path(install).resolve()
    for row in release["files"]:
        file = folder / row["name"]
        file.resolve().relative_to(folder)
        if (
            file.is_symlink()
            or not file.is_file()
            or file.stat().st_size != row["size"]
            or sha256(file) != row["sha256"]
        ):
            raise ValueError("Файл обновления изменён. Установка отменена.")
    payload = install / ("_internal/payload" if release["platform"] == "win10" else "payload")
    current = json.loads((payload / "manifest.json").read_text("utf8"))
    if current.get("platform") != release["platform"] or not (install / "ColorPro.exe").is_file():
        raise ValueError("Неверная папка установленного приложения")
    return [
        str(folder / release["installer"]),
        "/SILENT",
        "/NORESTART",
        "/DIR=" + str(install),
        "/COLORPROUPDATE=1",
        "/LOG=" + str(folder / "install.log"),
    ]


def launch_installer(release, folder):
    from colorpro import __version__

    if not getattr(sys, "frozen", False) or version_tuple(release["version"]) <= version_tuple(
        __version__
    ):
        raise ValueError("Обновление возможно только на более новую установленную версию")
    command = installer_command(release, folder, Path(sys.executable).parent)
    return subprocess.Popen(  # noqa: S603 -- exact product installer, hashes rechecked, no shell
        command, cwd=str(folder), close_fds=True
    )


def hold_application_mutex(platform):
    """Inno Setup refuses to overwrite a live GUI/batch process, including a second instance."""
    if os.name != "nt" or platform not in MUTEXES:
        return None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel.CreateMutexW(None, False, MUTEXES[platform])
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle  # Windows closes the handle at process exit, not when the UI merely hides.
