"""Validate independently captured Color Balance renders before recording fixtures."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from colorpro.build.compile_tone_bank import pixels
from colorpro.manual_balance import balance_lut


def verify(root, output):
    from colorcorrection.levels_operator import apply_rgb_lut

    if output.exists():
        raise FileExistsError("Do not replace a reference fixture")
    if "COMPLETE" not in (root / "balance-r1/events.txt").read_text().splitlines():
        raise ValueError("Incomplete reference capture")
    jobs = json.loads((root / "balance-jobs.json").read_text())
    source = pixels(root / "source.png")
    rows = []
    for index, (params, preserve) in enumerate(jobs):
        settings = {
            "shadows": params[0],
            "midtones": params[1],
            "highlights": params[2],
            "preserve_luminosity": preserve,
        }
        expected = pixels(root / "balance-r1" / f"balance_{index}.png")
        actual = apply_rgb_lut(source, balance_lut(settings))
        if not np.array_equal(actual, expected):
            raise ValueError(f"Mismatch in Color Balance case {index}")
        rows.append(
            {
                "settings": settings,
                "pixel_sha256": hashlib.sha256(expected.tobytes()).hexdigest(),
            }
        )
    if len(rows) < 78:
        raise ValueError("Insufficient independent references")
    output.write_text(
        json.dumps(
            {
                "reference_version": "15.0.0",
                "scope": "RGB8 sRGB, finite independent full-colour comparisons",
                "source": "Synthetic RGB grid; no photographs or model weights",
                "checks": rows,
            },
            indent=2,
        ),
        encoding="utf8",
    )
    print(json.dumps({"status": "PASS", "cases": len(rows)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify(args.root, args.output)
