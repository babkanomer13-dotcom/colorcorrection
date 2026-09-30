"""Write a compact distributable receipt without source photograph paths."""

import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024**2), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--qa", required=True, type=Path)
    args = parser.parse_args()
    audit = json.loads((args.qa / "win7-native-audit.json").read_text(encoding="utf8"))
    assert audit["static_checks_passed"]
    builds = {}
    hashes = []
    for flavor in ("win10", "win7"):
        filename = f"ColorPro-1.0.0-{flavor.replace('win', 'Win')}-x64-Setup.exe"
        installer = args.release / filename
        verified = json.loads(
            (args.qa / f"qa-{flavor}-installed-r1/VERIFIED.json").read_text(encoding="utf8")
        )
        assert verified["status"] == "PASS"
        old_install = args.qa / f"qa-install-{flavor}"
        assert not (old_install / "ColorPro.exe").exists()
        assert (old_install / "qa-user-file-preservation.txt").is_file()
        uninstall_log = (args.qa / f"qa-install-{flavor}-uninstall.log").read_text(
            encoding="utf-8-sig"
        )
        assert "Uninstallation process succeeded" in uninstall_log
        sha = digest(installer)
        hashes.append(f"{sha}  {filename}")
        builds[flavor] = dict(
            installer=filename,
            bytes=installer.stat().st_size,
            sha256=sha,
            installed_exe_sha256=verified["exe_sha256"],
            real_photo_parity=verified["photos"],
            jpeg_quality=100,
            jpeg_subsampling="4:4:4",
            install_test="PASS",
            uninstall_test="PASS",
            user_files_preserved=True,
            test_os=verified["diagnostic"]["os"],
            python=verified["diagnostic"]["python"],
            torch=verified["diagnostic"]["torch"],
            target_os_tested=(flavor == "win10"),
        )
    report = dict(
        version="1.0.0",
        model="V39 raw epoch 5",
        builds=builds,
        win7_native_static_audit=dict(passed=True, binaries=len(audit["binaries"])),
        digitally_signed=False,
        photographs_in_package=False,
        training_state_in_package=False,
        network_required=False,
    )
    (args.release / "BUILD-REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8"
    )
    (args.release / "SHA256SUMS.txt").write_text("\n".join(hashes) + "\n", encoding="ascii")
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
