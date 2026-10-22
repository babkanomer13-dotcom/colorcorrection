"""Compile synthetic reference tables and verify independent CC2014 RGB renders."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from colorpro.build.compile_tone_bank import pixels
from colorpro.manual_hsl import apply_hsl


def compile_bank(references, lightness_refs, source, output):
    if output.exists() or output.with_suffix(".json").exists():
        raise FileExistsError("Do not overwrite a measured bank")
    for root in (references, lightness_refs):
        if "COMPLETE" not in (root / "events.txt").read_text().splitlines():
            raise ValueError("Incomplete capture")
    saturation = np.empty((201, 32896, 2), dtype=np.uint8)
    lightness = np.empty((201, 256), dtype=np.uint8)
    high, low = np.tril_indices(256)
    for index in range(-100, 101):
        image = pixels(references / f"s_{index}.png")
        if image.shape != (256, 256, 3):
            raise ValueError("Invalid endpoint reference")
        endpoints = np.stack([image.min(2), image.max(2)], axis=2)
        if not np.array_equal(endpoints, endpoints.transpose(1, 0, 2)):
            raise ValueError("Saturation depends on channel identity")
        saturation[index + 100] = endpoints[high, low]
        lightness[index + 100] = pixels(lightness_refs / f"light_{index}.png")[0, :, 0]
    if not np.array_equal(
        saturation[100], np.stack([low, high], axis=1)
    ) or not np.array_equal(lightness[100], np.arange(256)):
        raise ValueError("Identity changed")
    source_pixels = pixels(source)
    checked = []
    for path in sorted(references.glob("rgb_*.png")) + sorted(
        lightness_refs.glob("light_*.png")
    ):
        if path.stem.startswith("rgb_"):
            hue, sat, light = map(int, path.stem.split("_")[1:])
        else:
            hue, sat, light = 0, 0, int(path.stem.split("_")[1])
        settings = {"hue": hue, "saturation": sat, "lightness": light}
        # CC2014's scripted zero adjustment still normalises RGB hue. An untouched
        # panel must not damage/recompress the user's result, so it bypasses HSL.
        if not any(settings.values()):
            continue
        actual = apply_hsl(source_pixels, settings, banks=(saturation, lightness))
        expected = pixels(path)
        if not np.array_equal(actual, expected):
            raise ValueError("Reference mismatch: " + path.name)
        checked.append(
            {
                "settings": settings,
                "pixel_sha256": hashlib.sha256(expected.tobytes()).hexdigest(),
            }
        )
    if len(checked) < 271:
        raise ValueError("Insufficient full-colour validation")
    with output.open("xb") as stream:
        np.savez_compressed(stream, saturation=saturation, lightness=lightness)
    metadata = {
        "schema": "cc2014-hsl-rgb8-v1",
        "reference_version": "15.0.0",
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "source": "Synthetic RGB grids; no photographs or model weights",
        "scope": "RGB8 sRGB master adjustment, Colorize disabled; finite independent full-colour validation",
        "neutral_policy": "All-zero controls bypass processing to preserve the file; Photoshop's scripted all-zero command may still quantise intermediate RGB values",
        "checks": checked,
    }
    with output.with_suffix(".json").open("x", encoding="utf8") as stream:
        json.dump(metadata, stream, indent=2)
    print(
        json.dumps(
            {
                "status": "PASS",
                "cases": len(checked),
                "bytes": output.stat().st_size,
                "sha256": metadata["sha256"],
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--lightness", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    compile_bank(args.references, args.lightness, args.source, args.output)
