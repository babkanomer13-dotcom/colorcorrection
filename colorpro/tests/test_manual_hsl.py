import hashlib
import json

import numpy as np
import pytest
from PIL import Image

from colorpro.levels import LevelsSession, defaults
from colorpro.manual_hsl import (
    ASSET,
    apply_hsl,
    hsl_defaults,
    load_hsl_bank,
    validate_hsl,
)


def test_hsl_reference_renders_match_cc2014():
    y, x = np.mgrid[0:256, 0:256]
    source = np.stack([x, y, (x * 73) % 256], axis=2).astype(np.uint8)
    source[0] = np.arange(256, dtype=np.uint8)[:, None]
    original = source.copy()
    metadata = json.loads(ASSET.with_suffix(".json").read_text(encoding="utf8"))
    assert len(metadata["checks"]) >= 271
    for row in metadata["checks"]:
        actual = apply_hsl(source, row["settings"])
        assert hashlib.sha256(actual.tobytes()).hexdigest() == row["pixel_sha256"], row[
            "settings"
        ]
    np.testing.assert_array_equal(source, original)


def test_hsl_contract_identity_extremes_and_chunks():
    for invalid in (
        {},
        {"hue": True, "saturation": 0, "lightness": 0},
        {"hue": 181, "saturation": 0, "lightness": 0},
        {"hue": 0, "saturation": -101, "lightness": 0},
        {"hue": 0, "saturation": 0, "lightness": 0.5},
    ):
        with pytest.raises(ValueError):
            validate_hsl(invalid)
    values = np.random.default_rng(2014).integers(0, 256, (513, 513, 3), dtype=np.uint8)
    assert apply_hsl(values, hsl_defaults()) is values
    settings = {"hue": -14, "saturation": 5, "lightness": 20}
    whole = apply_hsl(values, settings)
    parts = np.concatenate(
        [apply_hsl(part, settings) for part in np.array_split(values, 3)]
    )
    np.testing.assert_array_equal(whole, parts)
    assert np.all(
        apply_hsl(values, {"hue": 0, "saturation": 0, "lightness": 100}) == 255
    )
    assert np.all(
        apply_hsl(values, {"hue": 0, "saturation": 0, "lightness": -100}) == 0
    )
    assert not load_hsl_bank()[0].flags.writeable


def test_hsl_save_uses_full_resolution_and_preserves_original(tmp_path):
    source, output = tmp_path / "original.png", tmp_path / "original_с.png"
    pixels = np.random.default_rng(5).integers(0, 256, (137, 149, 3), dtype=np.uint8)
    Image.fromarray(pixels).save(source)
    output.write_bytes(source.read_bytes())
    before = source.read_bytes()
    settings = {"hue": 13, "saturation": -37, "lightness": 7}
    session = LevelsSession(output, source)
    data = session.save(defaults(), hsl=settings)
    with Image.open(output) as image:
        np.testing.assert_array_equal(np.asarray(image), apply_hsl(pixels, settings))
    assert source.read_bytes() == before
    assert data["manual_hsl"] == settings
