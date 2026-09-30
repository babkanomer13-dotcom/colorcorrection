"""Exercise a distributable EXE from an empty working directory, without developer paths."""

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, JpegImagePlugin


def pixel_hash(pixels):
    h, w = pixels.shape[:2]
    result = hashlib.sha256(w.to_bytes(8, "little") + h.to_bytes(8, "little"))
    result.update(np.ascontiguousarray(pixels).tobytes())
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("auto", "cpu"), default="cpu")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    clean_env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "COLORPRO_CONFIG", "COLORPRO_BUNDLE", "QT_PLUGIN_PATH"):
        clean_env.pop(key, None)
    clean_env["LOCALAPPDATA"] = str(args.output / "profile")
    clean_env["QT_QPA_PLATFORM"] = "offscreen"
    clean_env["PATH"] = os.pathsep.join(
        [str(Path(os.environ["WINDIR"]) / "System32"), os.environ["WINDIR"]]
    )

    def run(*extra):
        command = [str(args.exe)] + list(map(str, extra))
        done = subprocess.run(  # noqa: S603 -- explicitly supplied local QA executable, no shell
            command,
            env=clean_env,
            cwd=args.output,
            capture_output=True,
            timeout=240,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assert done.returncode == 0, (done.returncode, done.stderr.decode(errors="replace"), extra)

    run("--qa-smoke", args.output / "smoke/diagnostics.json", "--device", args.device)
    diagnostic = json.loads((args.output / "smoke/diagnostics.json").read_text(encoding="utf8"))
    assert diagnostic["status"] == "PASS", diagnostic
    review = json.loads(args.review.read_text(encoding="utf8"))["items"]
    selected = [r for r in review if r["review_order"] in (1, 17, 46, 47)]
    inputs = [r["source_path"] for r in selected]
    initial = [hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in inputs]
    run(
        "--batch",
        *inputs,
        "--output",
        args.output / "photos",
        "--format",
        "PNG",
        "--device",
        args.device,
    )
    reports = list((args.output / "photos").glob("*/report.json"))
    assert len(reports) == 1
    batch = json.loads(reports[0].read_text(encoding="utf8"))
    assert batch["state"] == "completed" and not batch["errors"] and len(batch["records"]) == 4
    checks = []
    for expected, record, original_sha in zip(selected, batch["records"], initial, strict=True):
        with Image.open(record["output"]) as image:
            digest = pixel_hash(np.asarray(image))
            assert image.info["icc_profile"] and image.getexif()[274] == 1
        same = digest == expected["assets"]["model"]["source_pixel_sha256"]
        unchanged = (
            hashlib.sha256(Path(expected["source_path"]).read_bytes()).hexdigest() == original_sha
        )
        checks.append(
            dict(order=expected["review_order"], pixel_identical=same, source_unchanged=unchanged)
        )
    run("--screenshot", args.output / "ui.png")
    assert (args.output / "ui.png").stat().st_size > 10000
    with Image.open(args.output / "smoke/synthetic-result.jpeg") as jpeg:
        assert JpegImagePlugin.get_sampling(jpeg) == 0
        assert all(v == 1 for table in jpeg.quantization.values() for v in table)
    receipt = dict(
        status="PASS"
        if all(c["pixel_identical"] and c["source_unchanged"] for c in checks)
        else "FAIL",
        exe=str(args.exe),
        exe_sha256=hashlib.sha256(args.exe.read_bytes()).hexdigest(),
        diagnostic=diagnostic,
        photos=checks,
        report=str(reports[0]),
        clean_working_directory=True,
        jpeg_quality=100,
        jpeg_subsampling="4:4:4",
        actual_windows7_execution=False,
    )
    (args.output / "VERIFIED.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print(json.dumps(receipt, ensure_ascii=False), flush=True)
    assert receipt["status"] == "PASS"


if __name__ == "__main__":
    main()
