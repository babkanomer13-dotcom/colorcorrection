"""Real installer acceptance in disposable directories; never update the user's app.

The tested installers are unmodified release artifacts. Their HKCU uninstall
entry and product Start Menu shortcuts are snapshotted and restored. The pinned
older baseline predates AllowNoIcons, so /NOICONS alone is insufficient there.
"""

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import winreg
from pathlib import Path

from colorpro.build.compact import inventory
from colorpro.updates import sha256


@contextlib.contextmanager
def preserved_registration(platform):
    guid = {
        "win10": "71C64124-2B1F-421C-B3E2-D204979CD1E5",
        "win7": "AA28C1D8-D7D9-4980-B74B-6961F8A11742",
    }[platform]
    name = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{" + guid + "}_is1"
    product = "ColorPro" if platform == "win10" else "ColorPro Win7"
    shortcuts = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs" / product
    shortcut_names = [product + ".lnk", "Проверка компонентов.lnk", "Удалить " + product + ".lnk"]
    saved_shortcuts = {
        n: (shortcuts / n).read_bytes() if (shortcuts / n).is_file() else None
        for n in shortcut_names
    }
    values = None
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, name, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY
        ) as key:
            assert winreg.QueryInfoKey(key)[0] == 0
            values = [winreg.EnumValue(key, i) for i in range(winreg.QueryInfoKey(key)[1])]
    except FileNotFoundError:
        pass
    try:
        yield name
    finally:
        for leaf, data in saved_shortcuts.items():
            path = shortcuts / leaf
            if data is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, name, 0, winreg.KEY_ALL_ACCESS | winreg.KEY_WOW64_64KEY
            ) as key:
                assert winreg.QueryInfoKey(key)[0] == 0
                for item in [
                    winreg.EnumValue(key, i)[0] for i in range(winreg.QueryInfoKey(key)[1])
                ]:
                    winreg.DeleteValue(key, item)
                if values is not None:
                    for item, value, kind in values:
                        winreg.SetValueEx(key, item, 0, kind, value)
            if values is None:
                winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, name, winreg.KEY_WOW64_64KEY)
        except FileNotFoundError:
            if values is not None:
                with winreg.CreateKeyEx(
                    winreg.HKEY_CURRENT_USER,
                    name,
                    0,
                    winreg.KEY_ALL_ACCESS | winreg.KEY_WOW64_64KEY,
                ) as key:
                    for item, value, kind in values:
                        winreg.SetValueEx(key, item, 0, kind, value)


def run_installer(exe, install, log, *options, timeout=900):
    result = subprocess.run(  # noqa: S603 -- supplied QA installer, explicit arguments, no shell
        [
            str(exe),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/NOICONS",
            "/TASKS=",
            "/DIR=" + str(install),
            "/LOG=" + str(log),
            *options,
        ],
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    print(log.name, "exit", result.returncode, flush=True)
    return result.returncode


def assert_distribution(install, expected):
    for name, row in expected.items():
        path = install / name
        assert path.is_file() and sha256(path) == row["sha256"], name


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=("win10", "win7"), required=True)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--offline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    expected = inventory(args.dist)
    upgrade = root / "upgrade"
    shutil.copytree(args.base, upgrade)
    sentinel = upgrade / "user-photos-untouched.txt"
    sentinel.write_text("user data must survive maintenance", encoding="utf8")
    component = upgrade / (
        "_internal/payload/weights/yunet.onnx"
        if args.platform == "win10"
        else "payload/weights/yunet.onnx"
    )
    original = component.read_bytes()
    component.write_bytes(b"damaged component for isolated acceptance")
    before = inventory(upgrade)
    with preserved_registration(args.platform) as registration:
        code = run_installer(args.installer, upgrade, root / "corrupt.log", "/COLORPROUPDATE=1")
        assert code != 0
        assert inventory(upgrade) == before, "Broken baseline must remain untouched"
        assert run_installer(args.installer, upgrade, root / "corrupt-manual.log") != 0
        assert inventory(upgrade) == before, "Manual patch must not reinstall a baseline"
        component.write_bytes(original)
        os.utime(component, (946684800, 946684800))
        stamp = component.stat().st_mtime_ns
        assert (
            run_installer(args.installer, upgrade, root / "upgrade.log", "/COLORPROUPDATE=1") == 0
        )
        assert "COMPACT_UPDATE: runtime verified; no component download." in (
            root / "upgrade.log"
        ).read_text("utf-8-sig")
        assert component.stat().st_mtime_ns == stamp
        assert sentinel.read_text("utf8") == "user data must survive maintenance"
        assert_distribution(upgrade, expected)
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            registration,
            0,
            winreg.KEY_ALL_ACCESS | winreg.KEY_WOW64_64KEY,
        ) as key:
            installed_version = winreg.QueryValueEx(key, "DisplayVersion")[0]
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, "99.0.0")
        assert (
            run_installer(args.installer, upgrade, root / "downgrade.log", "/COLORPROUPDATE=1") != 0
        )
        assert_distribution(upgrade, expected)
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            registration,
            0,
            winreg.KEY_ALL_ACCESS | winreg.KEY_WOW64_64KEY,
        ) as key:
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, installed_version)
        fresh = root / "fresh"
        assert run_installer(args.installer, fresh, root / "patch-on-empty.log") != 0
        assert not fresh.exists(), "A patch must not bootstrap a fresh installation"
        assert run_installer(args.offline, fresh, root / "fresh.log") == 0
        assert "OFFLINE_INSTALL: all components embedded; identical files are preserved." in (
            root / "fresh.log"
        ).read_text("utf-8-sig")
        assert_distribution(fresh, expected)
        # Deliberately different mtimes: Inno normally restores archived mtimes
        # on replacement, so comparing only original timestamps proves nothing.
        for name in expected:
            os.utime(fresh / name, (946684800, 946684800))
        stamps = {name: (fresh / name).stat().st_mtime_ns for name in expected}
        assert run_installer(args.offline, fresh, root / "repeat-offline.log") == 0
        assert_distribution(fresh, expected)
        assert all((fresh / n).stat().st_mtime_ns == stamp for n, stamp in stamps.items())
        repair = fresh / component.relative_to(upgrade)
        repair.write_bytes(b"damage to test selective offline repair")
        assert run_installer(args.offline, fresh, root / "repair-offline.log") == 0
        assert_distribution(fresh, expected)
        assert all(
            (fresh / n).stat().st_mtime_ns == stamp
            for n, stamp in stamps.items()
            if fresh / n != repair
        )
        # A full installer must not downgrade either.
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            registration,
            0,
            winreg.KEY_ALL_ACCESS | winreg.KEY_WOW64_64KEY,
        ) as key:
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, "99.0.0")
        assert run_installer(args.offline, fresh, root / "offline-downgrade.log") != 0
        assert_distribution(fresh, expected)
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            registration,
            0,
            winreg.KEY_ALL_ACCESS | winreg.KEY_WOW64_64KEY,
        ) as key:
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, installed_version)
        env = os.environ.copy()
        env["LOCALAPPDATA"] = str(root / "profile")
        env["QT_QPA_PLATFORM"] = "offscreen"
        smoke = subprocess.run(  # noqa: S603 -- verified app in the fresh QA directory
            [
                str(fresh / "ColorPro.exe"),
                "--qa-smoke",
                str(root / "smoke.json"),
                "--device",
                "cpu",
            ],
            env=env,
            cwd=root,
            timeout=180,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assert smoke.returncode == 0
        assert json.loads((root / "smoke.json").read_text("utf8"))["status"] == "PASS"
        kept = fresh / "user-result.txt"
        kept.write_text("Uninstallation must keep user files", encoding="utf8")
        uninstall = subprocess.run(  # noqa: S603 -- uninstaller from the isolated QA install
            [
                str(fresh / "unins000.exe"),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/LOG=" + str(root / "uninstall.log"),
            ],
            timeout=180,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assert uninstall.returncode == 0
        assert kept.read_text("utf8") == "Uninstallation must keep user files"
        assert not (fresh / "ColorPro.exe").exists()
    report = dict(
        platform=args.platform,
        status="PASS",
        compact_upgrade=True,
        installer_sha256=sha256(args.installer),
        offline_sha256=sha256(args.offline),
        patch_never_bootstraps=True,
        full_rerun_preserves_all_distribution_mtimes=True,
        full_repairs_only_damaged_files=True,
        unchanged_runtime_not_replaced=True,
        corrupt_baseline_no_mutation=True,
        downgrade_blocked=True,
        single_exe_fresh_install=True,
        installed_smoke=True,
        uninstall_preserves_user_files=True,
        user_registration_and_shortcuts_restored=True,
        actual_windows7_execution=False,
    )
    (root / "VERIFIED.json").write_text(json.dumps(report, indent=2), encoding="utf8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
