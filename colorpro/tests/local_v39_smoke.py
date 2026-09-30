"""Explicit real-image acceptance test. Writes only to supplied private output."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

from colorpro.launcher import initialize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    args = parser.parse_args()
    config = initialize()
    import numpy as np
    from PIL import Image

    from colorcorrection.classic_face_inference import pixel_hash
    from colorpro.batch import Control, run_batch
    from colorpro.files import collect_inputs

    items = json.loads(args.review.read_text(encoding="utf8"))["items"]
    selected = [r for r in items if r["review_order"] in (1, 17, 46, 47)]
    inputs, errors = collect_inputs([r["source_path"] for r in selected])
    assert len(inputs) == 4 and not errors
    source_hashes = {i.path: hashlib.sha256(Path(i.path).read_bytes()).hexdigest() for i in inputs}

    def emit(e):
        if e["type"] in ("stage", "result", "ready"):
            print(json.dumps(e, ensure_ascii=False), flush=True)

    report = run_batch(inputs, args.output, "v39", args.device, "PNG", Control(), emit)
    checks = []
    assert report["state"] == "completed" and not report["errors"], report
    for item, record in zip(selected, report["records"], strict=True):
        with Image.open(record["output"]) as image:
            actual = pixel_hash(np.asarray(image.convert("RGB")))
            assert image.info["icc_profile"]
            assert image.getexif()[274] == 1
        expected = item["assets"]["model"]["source_pixel_sha256"]
        assert actual == expected, (item["review_order"], actual, expected)
        assert (
            hashlib.sha256(Path(item["source_path"]).read_bytes()).hexdigest()
            == source_hashes[item["source_path"]]
        )
        checks.append(dict(order=item["review_order"], pixel_identical=True, source_unchanged=True))
    imported = Path(sys.modules["colorcorrection.classic_face_inference"].__file__)
    assert imported.is_relative_to(Path(config["runtime_root"]))
    receipt = dict(
        status="PASS",
        checkpoint_sha256=report["weights_sha256"],
        checks=checks,
        runtime_module=str(imported),
        report=str(Path(report["output"]) / "report.json"),
        external_upload=False,
    )
    with (args.output / "acceptance.json").open("x", encoding="utf8") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2)
    print(json.dumps(receipt, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
