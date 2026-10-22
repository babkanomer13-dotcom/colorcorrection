"""Compile synthetic CC2014 atlases; reject incomplete or unverified references."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


def pixels(path):
    with Image.open(path) as im:
        if im.mode != "RGB":
            raise ValueError("RGB8 reference required: " + str(path))
        return np.array(im)


def compile_bank(atlases, verification, output):
    if output.exists() or output.with_suffix(".json").exists():
        raise FileExistsError("Do not overwrite a measured bank")
    if (
        "COMPLETE"
        not in (atlases / "events.txt")
        .read_text(encoding="utf8", errors="replace")
        .splitlines()
    ):
        raise ValueError("Atlas capture is not complete")
    bank = np.empty((301, 151, 256), dtype=np.uint8)
    for b in range(-150, 151):
        image = pixels(atlases / (f"brightness_{b}.png"))
        if (
            image.shape != (151, 256, 3)
            or not np.array_equal(image[:, :, 0], image[:, :, 1])
            or not np.array_equal(image[:, :, 1], image[:, :, 2])
        ):
            raise ValueError("Invalid grayscale atlas")
        bank[b + 150] = image[:, :, 0]
    if not np.array_equal(bank[150, 50], np.arange(256, dtype=np.uint8)):
        raise ValueError("Identity changed")
    if np.any(np.diff(bank.astype(np.int16), axis=2) < 0):
        raise ValueError("Brightness/contrast must be monotonic")
    # These are independent full-colour renders, not the calibration atlases.
    source = pixels(verification / "identity.png")
    checked = []
    for path in sorted(verification.glob("bc_*.png")):
        _, b, c = path.stem.split("_")
        expected = pixels(path)
        actual = bank[int(b) + 150, int(c) + 50][source]
        if not np.array_equal(actual, expected):
            raise ValueError("Reference mismatch: " + path.name)
        checked.append(
            {
                "brightness": int(b),
                "contrast": int(c),
                "pixel_sha256": hashlib.sha256(expected.tobytes()).hexdigest(),
            }
        )
    if len(checked) < 14:
        raise ValueError("Insufficient independent verification")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        np.savez_compressed(stream, lut=bank)
    metadata = {
        "schema": "cc2014-brightness-contrast-rgb8-v1",
        "reference_version": "15.0.0",
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "shape": list(bank.shape),
        "use_legacy": False,
        "brightness_range": [-150, 150],
        "contrast_range": [-50, 100],
        "source": "Synthetic grayscale atlases; no photographs or model weights",
        "independent_rgb_checks": checked,
        "scope": "sRGB RGB8, Photoshop CC2014 15.0.0, default non-legacy adjustment; finite full-colour validation",
    }
    with output.with_suffix(".json").open("x", encoding="utf8") as stream:
        json.dump(metadata, stream, indent=2)
    print(
        json.dumps(
            {
                "status": "PASS",
                "cases": 301 * 151,
                "bytes": output.stat().st_size,
                "sha256": metadata["sha256"],
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--atlases", type=Path, required=True)
    parser.add_argument("--verification", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    compile_bank(args.atlases, args.verification, args.output)
