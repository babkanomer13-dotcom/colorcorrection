import hashlib
import io
import json

import pytest

from colorpro import updates as u


def fixture_release(platform="win10", version="1.2.0"):
    name = "ColorPro-{}-{}-x64-Setup.exe".format(
        version, "Win10" if platform == "win10" else "Win7"
    )
    data = b"synthetic installer; never executed"
    sha = hashlib.sha256(data).hexdigest()
    asset = dict(
        name=name,
        size=len(data),
        digest="sha256:" + sha,
        state="uploaded",
        browser_download_url="https://github.com/"
        + u.REPOSITORY
        + "/releases/download/colorpro-v"
        + version
        + "/"
        + name,
    )
    manifest = dict(
        schema="colorpro-update-v1",
        version=version,
        platform=platform,
        installer=name,
        files=[dict(name=name, size=len(data), sha256=sha)],
    )
    return manifest, {name: asset}, data


class Response(io.BytesIO):
    def __init__(self, data, status=200, headers=None):
        super().__init__(data)
        self.status = status
        self.headers = headers or {}


def test_version_and_hosts():
    assert u.version_tuple("1.10.0") > u.version_tuple("1.9.9")
    for value in ["v1.2.3", "1.2", "../1.2.3", "1.2.3-beta"]:
        with pytest.raises(ValueError):
            u.version_tuple(value)
    for url in [
        "http://github.com/x",
        "https://github.com.evil/x",
        "file:///tmp/example",
        "https://u:p@github.com/x",
        "https://github.com:8443/x",
    ]:
        assert not u.safe_url(url)
    assert u.safe_url("https://release-assets.githubusercontent.com/signed")


@pytest.mark.parametrize(
    "change", ["platform", "sha", "size", "path", "duplicate", "url", "digest", "missing"]
)
def test_manifest_rejects_bad_release(change):
    m, assets, _ = fixture_release()
    a = next(iter(assets.values()))
    if change == "platform":
        m["platform"] = "win7"
    elif change == "sha":
        m["files"][0]["sha256"] = "0" * 64
    elif change == "size":
        m["files"][0]["size"] += 1
    elif change == "path":
        m["files"][0]["name"] = "../evil.exe"
    elif change == "duplicate":
        m["files"].append(m["files"][0])
    elif change == "url":
        a["browser_download_url"] = "https://github.com/other/other/x"
    elif change == "digest":
        a["digest"] = ""
    elif change == "missing":
        assets.clear()
    with pytest.raises(ValueError):
        u.validate_manifest(m, assets, "1.2.0", "win10")


@pytest.mark.parametrize("platform", ["win10", "win7"])
def test_download_verified_cached_and_install_command(tmp_path, monkeypatch, platform):
    m, assets, data = fixture_release(platform)
    release = u.validate_manifest(m, assets, "1.2.0", platform)
    monkeypatch.setattr(u, "request", lambda *args: Response(data))
    folder = u.download_update(release, tmp_path / "cache")
    monkeypatch.setattr(u, "request", lambda *args: pytest.fail("cache was not reused"))
    assert u.download_update(release, tmp_path / "cache") == folder
    install = tmp_path / "installed"
    payload = install / ("_internal/payload" if platform == "win10" else "payload")
    payload.mkdir(parents=True)
    (payload / "manifest.json").write_text(json.dumps(dict(platform=platform)))
    (install / "ColorPro.exe").write_bytes(b"old exe")
    cmd = u.installer_command(release, folder, install)
    assert cmd[0] == str(folder / m["installer"])
    assert "/DIR=" + str(install) in cmd
    (folder / m["installer"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="изменён"):
        u.installer_command(release, folder, install)


@pytest.mark.parametrize("status", [200, 206])
def test_resume_download(tmp_path, monkeypatch, status):
    m, assets, data = fixture_release()
    release = u.validate_manifest(m, assets, "1.2.0", "win10")
    folder = tmp_path / "win10-1.2.0"
    folder.mkdir()
    (folder / (m["installer"] + ".part")).write_bytes(data[:5])

    def request(url, headers):
        assert headers["Range"] == "bytes=5-"
        return Response(
            data[5:] if status == 206 else data,
            status,
            {"Content-Range": f"bytes 5-{len(data) - 1}/{len(data)}"},
        )

    monkeypatch.setattr(u, "request", request)
    u.download_update(release, tmp_path)
    assert (folder / m["installer"]).read_bytes() == data


def test_corrupt_download_never_installed(tmp_path, monkeypatch):
    m, assets, data = fixture_release()
    r = u.validate_manifest(m, assets, "1.2.0", "win10")
    monkeypatch.setattr(u, "request", lambda *args: Response(b"x" * len(data)))
    with pytest.raises(ValueError, match="повреждена"):
        u.download_update(r, tmp_path)
    assert not list(tmp_path.rglob("*.exe"))
    assert not list(tmp_path.rglob("*.part"))


def test_cancel_leaves_install_untouched(tmp_path, monkeypatch):
    m, assets, _ = fixture_release()
    r = u.validate_manifest(m, assets, "1.2.0", "win10")
    monkeypatch.setattr(u, "request", lambda *a: pytest.fail("cancelled download attempted"))
    with pytest.raises(u.Cancelled):
        u.download_update(r, tmp_path, cancelled=lambda: True)
    assert not list(tmp_path.rglob("*.exe"))


def test_channels_drafts_and_current(monkeypatch):
    m, assets, _ = fixture_release("win7")
    meta_name = "ColorPro-1.2.0-win7-update.json"
    meta_raw = json.dumps(m).encode()
    assets[meta_name] = dict(
        name=meta_name,
        size=len(meta_raw),
        state="uploaded",
        digest="sha256:" + hashlib.sha256(meta_raw).hexdigest(),
        browser_download_url="https://github.com/"
        + u.REPOSITORY
        + "/releases/download/colorpro-v1.2.0/"
        + meta_name,
    )
    releases = [
        dict(tag_name="colorpro-v9.0.0", draft=True),
        dict(tag_name="colorpro-v8.0.0", prerelease=True),
        dict(tag_name="v6.0.0"),
        dict(tag_name="colorpro-v1.2.0", assets=list(assets.values())),
    ]
    monkeypatch.setattr(u, "read_json", lambda url, asset=None: m if asset else releases)
    assert u.latest_release("1.1.0", "win10") is None
    assert u.latest_release("1.2.0", "win7") is None
    assert u.latest_release("1.1.0", "win7")["version"] == "1.2.0"


def test_source_install_forbidden(monkeypatch, tmp_path):
    monkeypatch.setattr(u.sys, "frozen", False, raising=False)
    with pytest.raises(ValueError):
        u.launch_installer(dict(version="1.2.0"), tmp_path)


@pytest.mark.parametrize("suffix", ["-1.bin", "-1a.bin", "-2.bin"])
def test_inno_disk_slices(suffix):
    m, assets, _ = fixture_release()
    name = m["installer"][:-4] + suffix
    a = dict(next(iter(assets.values())))
    a["browser_download_url"] = a["browser_download_url"].rsplit("/", 1)[0] + "/" + name
    a["name"] = name
    assets[name] = a
    m["files"].append(dict(name=name, size=a["size"], sha256=a["digest"][7:]))
    assert len(u.validate_manifest(m, assets, "1.2.0", "win10")["files"]) == 2


def test_manifest_download_hash(monkeypatch):
    monkeypatch.setattr(u, "request", lambda *args: Response(b"{}"))
    with pytest.raises(ValueError, match="повреждено"):
        u.read_json("https://github.com/x", dict(size=2, sha256="0" * 64))
