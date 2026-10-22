"""Verify held-out synthetic RGB renders and export portable regression hashes."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from colorpro.levels import defaults
from colorpro.manual_hsl import apply_hsl, hsl_defaults
from colorpro.manual_tone import combined_lut


def synthetic_source():
    return np.random.default_rng(20261023).integers(
        0, 256, (512, 512, 3), dtype=np.uint8
    )


def render(source, settings):
    from colorcorrection.levels_operator import apply_rgb_lut

    result = apply_rgb_lut(
        source,
        combined_lut(
            settings.get("levels", defaults()),
            settings.get("tone"),
            settings.get("balance"),
        ),
    )
    return apply_hsl(result, settings.get("hsl", hsl_defaults()))


def verify(references, jobs, output):
    if output.exists():
        raise FileExistsError("Never overwrite accepted reference hashes")
    if "COMPLETE" not in (references / "events.txt").read_text(encoding="utf8"):
        raise ValueError("Incomplete reference capture")
    source = synthetic_source()
    with Image.open(references / "identity.png") as im:
        np.testing.assert_array_equal(np.asarray(im), source)
    settings = json.loads(jobs.read_text(encoding="utf8"))
    if len(settings) != 48:
        raise ValueError("Expected all 48 held-out checks")
    checked = []
    for index, row in enumerate(settings):
        with Image.open(references / f"pipeline_{index}.png") as im:
            expected = np.asarray(im)
        actual = render(source, row)
        if not np.array_equal(expected, actual):
            difference = np.abs(expected.astype(np.int16) - actual)
            raise ValueError(
                f"Case {index}, {row['mode']}: maximum difference {difference.max()}, "
                f"different channels {np.count_nonzero(difference)}"
            )
        checked.append(
            {
                "settings": row,
                "pixel_sha256": hashlib.sha256(expected.tobytes()).hexdigest(),
            }
        )
    receipt = {
        "schema": "colorpro-heldout-manual-rgb8-v1",
        "reference_version": "15.0.0",
        "source": "PCG64 seed 20261023, uint8 RGB, 512 x 512; synthetic, no photos",
        "source_pixel_sha256": hashlib.sha256(source.tobytes()).hexdigest(),
        "scope": "sRGB RGB8, independent settings and sequential combinations; finite validation",
        "checks": checked,
    }
    with output.open("x", encoding="utf8") as stream:
        json.dump(receipt, stream, indent=2)
    print("PASS:", len(checked), "held-out full RGB reference renders")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--jobs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify(args.references, args.jobs, args.output)
