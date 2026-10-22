"""Held-out Photoshop reference hashes, independent of calibration atlases."""

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from colorpro.build.verify_manual_reference import render, synthetic_source
from colorpro.levels import LevelsSession, defaults


def reference():
    return json.loads(
        Path(__file__).with_name("manual_reference.json").read_text(encoding="utf8")
    )


def test_heldout_cc2014_independent_and_combined_tools():
    metadata = reference()
    source = synthetic_source()
    assert (
        hashlib.sha256(source.tobytes()).hexdigest() == metadata["source_pixel_sha256"]
    )
    assert len(metadata["checks"]) == 48
    for row in metadata["checks"]:
        actual = render(source, row["settings"])
        assert hashlib.sha256(actual.tobytes()).hexdigest() == row["pixel_sha256"], row[
            "settings"
        ]


def test_combined_full_resolution_save_uses_verified_recipe(tmp_path):
    metadata = reference()
    row = metadata["checks"][36]
    recipe = row["settings"]
    pixels = synthetic_source()
    source = tmp_path / "original.png"
    output = tmp_path / "original_с.png"
    Image.fromarray(pixels).save(source)
    output.write_bytes(source.read_bytes())
    before = source.read_bytes()
    session = LevelsSession(output, source)
    session.save(
        recipe.get("levels", defaults()),
        tone=recipe.get("tone"),
        hsl=recipe.get("hsl"),
        balance=recipe.get("balance"),
    )
    with Image.open(output) as image:
        assert (
            hashlib.sha256(np.asarray(image).tobytes()).hexdigest()
            == row["pixel_sha256"]
        )
    assert source.read_bytes() == before
