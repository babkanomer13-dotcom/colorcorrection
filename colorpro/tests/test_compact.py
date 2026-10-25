import pytest

from colorpro import updates
from colorpro.build.compact import generate, plan


def row(hash, size=10):
    return dict(sha256=hash * 64, size=size)


def make_runtime(path, platform="win10"):
    prefix = "_internal/" if platform == "win10" else ""
    names = [
        "payload/manifest.json",
        "payload/weights/v39.pt",
        "payload/weights/yunet.onnx",
    ]
    names += (
        ["python312.dll", "PySide6/Qt6Core.dll"]
        if platform == "win10"
        else ["python38.dll", "PySide2/Qt5Core.dll"]
    )
    for name in names:
        target = path / (prefix + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((platform + name).encode())


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
        make_runtime(path)
    report = generate(dist, [base], tmp_path / "plan", "win10")
    assert report["download_bytes"] == 0
    assert set(report["changed"]) == {"ColorPro.exe"}
    assert "runtime.dll" in report["required"]
    assert (tmp_path / "plan/targets.txt").read_text() == "ColorPro.exe"
    assert "runtime.dll" not in (tmp_path / "plan/anchors.txt").read_text()
    assert report["verification"] == "baseline-and-changed-files"
    assert not (tmp_path / "plan/baseline.iss").exists()


def test_archived_inventory_has_identical_compact_plan(tmp_path):
    from colorpro.build.compact import inventory

    dist, base = tmp_path / "dist", tmp_path / "base"
    for path in (dist, base):
        path.mkdir()
        (path / "runtime.dll").write_bytes(b"unchanged runtime")
        (path / "ColorPro.exe").write_bytes(path.name.encode())
        make_runtime(path)
    physical = generate(dist, [base], tmp_path / "physical", "win10")
    archived = generate(
        dist, [], tmp_path / "archived", "win10", baseline_inventories=[inventory(base)]
    )
    assert physical == archived
    assert (tmp_path / "physical/files.iss").read_bytes() == (
        tmp_path / "archived/files.iss"
    ).read_bytes()


@pytest.mark.parametrize("platform", ["win10", "win7"])
def test_fast_check_accepts_only_known_channel_manifests(tmp_path, platform):
    from colorpro.build.compact import inventory

    current, older = tmp_path / "current", tmp_path / "older"
    prefix = "_internal/" if platform == "win10" else ""
    manifest = prefix + "payload/manifest.json"
    for path in (current, older):
        make_runtime(path, platform)
        (path / "ColorPro.exe").write_bytes(path.name.encode())
        (path / manifest).write_bytes(path.name.encode())
    output = tmp_path / "plan"
    generate(current, [older], output, platform)
    rows = (output / "baselines.txt").read_text().splitlines()
    assert set(rows) == {
        updates.sha256(path / manifest) + "|" + manifest.replace("/", "\\")
        for path in (current, older)
    }
    assert len((output / "anchors.txt").read_text().splitlines()) == 5
    wrong_channel = inventory(older)
    wrong_channel.pop(manifest)
    with pytest.raises(ValueError, match="identity"):
        generate(
            current,
            [],
            tmp_path / "bad",
            platform,
            baseline_inventories=[wrong_channel],
        )
    assert not (tmp_path / "bad").exists()


def test_archived_inventory_rejects_invalid_digest_and_path():
    from colorpro.build.compact import validated_inventory

    for data in (
        {},
        {"ColorPro.exe": {"sha256": "bad", "size": 10}},
        {"ColorPro.exe": row("a"), "../bad": row("b")},
        {"ColorPro.exe": row("a", -1)},
    ):
        with pytest.raises(ValueError):
            validated_inventory(data)


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
            (tmp_path / f"ColorPro-{__version__}-{channel}-update.json").read_text(
                "utf8"
            )
        )
        assert manifest["kind"] == "compact"
        assert len(manifest["files"]) == 1
        assert manifest["files"][0]["name"].endswith("-Setup.exe")
    assert (tmp_path / "SHA256SUMS.txt").read_text("ascii").count("-Offline.exe") == 2
