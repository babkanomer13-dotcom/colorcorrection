import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from colorpro.levels import LevelsSession, defaults
from colorpro.manual_balance import balance_defaults, balance_lut, validate_balance


def test_color_balance_cc2014_rgb_references():
    from colorcorrection.levels_operator import apply_rgb_lut

    y, x = np.mgrid[0:256, 0:256]
    source = np.stack([x, y, (x * 73) % 256], axis=2).astype(np.uint8)
    source[0] = np.arange(256, dtype=np.uint8)[:, None]
    metadata = json.loads(
        Path(__file__).with_name("balance_reference.json").read_text(encoding="utf8")
    )
    assert len(metadata["checks"]) >= 78
    for row in metadata["checks"]:
        actual = apply_rgb_lut(source, balance_lut(row["settings"]))
        assert hashlib.sha256(actual.tobytes()).hexdigest() == row["pixel_sha256"], row[
            "settings"
        ]


def test_color_balance_validation_and_neutral():
    settings = balance_defaults()
    np.testing.assert_array_equal(
        balance_lut(settings), np.tile(np.arange(256), (3, 1))
    )
    settings["midtones"] = [20, 20, 20]
    np.testing.assert_array_equal(
        balance_lut(settings), np.tile(np.arange(256), (3, 1))
    )
    for values in ([101, 0, 0], [0, 0], [True, 0, 0], [0.0, 0, 0]):
        settings["midtones"] = values
        with pytest.raises(ValueError):
            validate_balance(settings)
    settings = balance_defaults()
    settings["preserve_luminosity"] = 1
    with pytest.raises(ValueError):
        validate_balance(settings)


def test_color_balance_full_resolution_save(tmp_path):
    from colorcorrection.levels_operator import apply_rgb_lut

    source, output = tmp_path / "original.png", tmp_path / "original_с.png"
    pixels = np.random.default_rng(51).integers(0, 256, (137, 149, 3), dtype=np.uint8)
    Image.fromarray(pixels).save(source)
    output.write_bytes(source.read_bytes())
    before = source.read_bytes()
    settings = balance_defaults()
    settings["midtones"] = [13, -27, 10]
    session = LevelsSession(output, source)
    data = session.save(defaults(), balance=settings)
    with Image.open(output) as image:
        np.testing.assert_array_equal(
            np.asarray(image), apply_rgb_lut(pixels, balance_lut(settings))
        )
    assert source.read_bytes() == before
    assert data["manual_color_balance"] == settings
