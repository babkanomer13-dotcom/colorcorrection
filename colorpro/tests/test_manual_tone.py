import numpy as np
import pytest
from PIL import Image

from colorpro.levels import LevelsSession, defaults
from colorpro.manual_tone import brightness_contrast_lut, tone_defaults, validate_tone


def test_brightness_contrast_cc2014_independent_rgb_references():
    import hashlib
    import json

    from colorpro.manual_tone import ASSET, load_tone_bank

    metadata = json.loads(ASSET.with_suffix(".json").read_text(encoding="utf8"))
    y, x = np.mgrid[0:256, 0:256]
    source = np.stack([x, y, (x * 73) % 256], axis=2).astype(np.uint8)
    source[0] = np.arange(256, dtype=np.uint8)[:, None]
    assert len(metadata["independent_rgb_checks"]) >= 14
    for row in metadata["independent_rgb_checks"]:
        settings = {key: row[key] for key in ("brightness", "contrast")}
        actual = brightness_contrast_lut(settings)[source]
        assert hashlib.sha256(actual.tobytes()).hexdigest() == row["pixel_sha256"], (
            settings
        )
    bank = load_tone_bank()
    assert not bank.flags.writeable
    assert np.all(np.diff(bank.astype(np.int16), axis=2) >= 0)


def test_tone_contract_and_neutral_does_not_require_photoshop():
    assert np.array_equal(
        brightness_contrast_lut(tone_defaults()), np.arange(256, dtype=np.uint8)
    )
    for bad in (
        {},
        {"brightness": 151, "contrast": 0},
        {"brightness": 0, "contrast": -51},
        {"brightness": 0.5, "contrast": 0},
        {"brightness": False, "contrast": 0},
    ):
        with pytest.raises(ValueError):
            validate_tone(bad)


def test_tone_composes_after_levels_and_records_saved_recipe(tmp_path, monkeypatch):
    import colorpro.manual_tone as tone

    # Synthetic data isolates save/composition from the independent Adobe checks.
    fake = np.minimum(np.arange(256, dtype=np.int16) + 8, 255).astype(np.uint8)
    monkeypatch.setattr(tone, "brightness_contrast_lut", lambda settings: fake)
    source, output = tmp_path / "source.png", tmp_path / "source_с.png"
    Image.new("RGB", (30, 40), (100, 120, 140)).save(source)
    output.write_bytes(source.read_bytes())
    before = source.read_bytes()
    session = LevelsSession(output, source)
    data = session.save(defaults(), {"brightness": 8, "contrast": 0})
    assert data["manual_brightness_contrast"] == {"brightness": 8, "contrast": 0}
    assert source.read_bytes() == before
    with Image.open(output) as image:
        assert image.getpixel((0, 0)) == (108, 128, 148)


def test_bank_hash_and_shape_fail_closed(tmp_path, monkeypatch):
    import hashlib
    import json

    import colorpro.manual_tone as tone

    asset = tmp_path / "bank.npz"
    meta = asset.with_suffix(".json")
    monkeypatch.setattr(tone, "ASSET", asset)
    tone.load_tone_bank.cache_clear()
    with asset.open("xb") as stream:
        np.savez_compressed(stream, lut=np.zeros((3, 4, 5), dtype=np.uint8))
    metadata = {
        "schema": "cc2014-brightness-contrast-rgb8-v1",
        "reference_version": "15.0.0",
        "sha256": "0" * 64,
    }
    meta.write_text(json.dumps(metadata), encoding="utf8")
    with pytest.raises(ValueError, match="повреждена"):
        brightness_contrast_lut({"brightness": 1, "contrast": 0})
    metadata["sha256"] = hashlib.sha256(asset.read_bytes()).hexdigest()
    meta.write_text(json.dumps(metadata), encoding="utf8")
    with pytest.raises(ValueError, match="Неполная"):
        brightness_contrast_lut({"brightness": 1, "contrast": 0})
    tone.load_tone_bank.cache_clear()
