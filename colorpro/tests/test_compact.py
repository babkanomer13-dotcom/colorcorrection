import pytest

from colorpro import updates
from colorpro.build.compact import plan


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
