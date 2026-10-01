import pytest

from colorpro import updates
from colorpro.build.compact import generate, plan


def row(hash, size=10):
    return dict(sha256=hash * 64, size=size)


def test_compact_compares_every_supported_version():
    old = {"ColorPro.exe": row("a"), "runtime.dll": row("b"), "readme.txt": row("c")}
    middle = dict(old, **{"readme.txt": row("d")})
    new = dict(middle, **{"ColorPro.exe": row("e")})
    changed, required = plan(new, [old, middle])
    assert set(changed) == {"ColorPro.exe", "readme.txt"}
    assert set(required) == {"runtime.dll"}


def test_compact_never_hides_a_model_or_runtime_upgrade():
    base = {"ColorPro.exe": row("a"), "weights/v39.pt": row("b")}
    with pytest.raises(ValueError, match="Runtime/model"):
        plan(dict(base, **{"weights/v39.pt": row("c")}), [base])
    with pytest.raises(ValueError, match="Removed"):
        plan({"ColorPro.exe": row("a")}, [base])
    with pytest.raises(ValueError, match="baseline"):
        plan(base, [])


def test_compact_manifest_is_backwards_compatible():
    from colorpro.tests.test_updates import fixture_release

    manifest, assets, _ = fixture_release(version="1.3.0")
    manifest["kind"] = "compact"
    verified = updates.validate_manifest(manifest, assets, "1.3.0", "win10")
    assert verified["kind"] == "compact"
    assert len(verified["files"]) == 1
    manifest["kind"] = "unsupported"
    with pytest.raises(ValueError, match="тип"):
        updates.validate_manifest(manifest, assets, "1.3.0", "win10")


def test_offline_contains_every_file_with_hash_skip_and_no_download(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "ColorPro.exe").write_bytes(b"app")
    (dist / "lib").mkdir()
    (dist / "lib/runtime.dll").write_bytes(b"runtime")
    result = generate(dist, [], tmp_path / "plan", "win10", offline=True)
    assert result["schema"] == "colorpro-offline-v1"
    assert result["download_bytes"] == 0 and not result["required"]
    assert set(result["changed"]) == {"ColorPro.exe", "lib/runtime.dll"}
    code = (tmp_path / "plan/files.iss").read_text("utf8")
    assert code.count("Check: NeedsFile(") == 2
    assert 'DestDir: "{app}\\lib"' in code
    assert not (tmp_path / "plan/baseline.iss").exists()


def test_compact_has_no_first_install_fallback(tmp_path):
    dist, base = tmp_path / "dist", tmp_path / "base"
    for path in (dist, base):
        path.mkdir()
        (path / "runtime.dll").write_bytes(b"runtime")
        (path / "ColorPro.exe").write_bytes(path.name.encode())
    report = generate(dist, [base], tmp_path / "plan", "win10")
    assert report["download_bytes"] == 0
    assert set(report["changed"]) == {"ColorPro.exe"}
    assert set(report["required"]) == {"runtime.dll"}
    assert not (tmp_path / "plan/baseline.iss").exists()


def test_full_installer_is_not_downloaded_by_updater(tmp_path):
    import json

    from colorpro import __version__
    from colorpro.build.publish_release import prepare

    for channel in ("win10", "win7"):
        for kind in ("Setup", "Offline"):
            name = "ColorPro-{}-{}-x64-{}.exe".format(
                __version__, channel.replace("win", "Win"), kind
            )
            (tmp_path / name).write_bytes(kind.encode())
        (tmp_path / (channel + "-compact.json")).write_text(
            json.dumps(dict(version=__version__, platform=channel)), encoding="utf8"
        )
    assets = prepare(tmp_path)
    assert len(assets) == 6
    for channel in ("win10", "win7"):
        manifest = json.loads(
            (tmp_path / f"ColorPro-{__version__}-{channel}-update.json").read_text("utf8")
        )
        assert manifest["kind"] == "compact"
        assert len(manifest["files"]) == 1
        assert manifest["files"][0]["name"].endswith("-Setup.exe")
    assert (tmp_path / "SHA256SUMS.txt").read_text("ascii").count("-Offline.exe") == 2
