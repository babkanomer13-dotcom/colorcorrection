"""Offline diagnostics for the actual installed application, without a dev environment."""

import json
import platform
import sys
import traceback
from pathlib import Path


def diagnose(destination, *, smoke=False, device="auto"):
    from colorpro.config import load_config, verify_runtime

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    report = dict(status="FAIL", os=platform.platform(), python=sys.version, smoke=smoke)
    try:
        config = load_config()
        verify_runtime(config)
        import cv2
        import numpy as np
        import torch
        from PIL import Image

        from colorpro.engine import Engine
        from colorpro.files import collect_inputs, read_image, save_result

        report.update(
            torch=torch.__version__,
            opencv=cv2.__version__,
            numpy=np.__version__,
            platform=config.get("platform", "local"),
            weights=config["checkpoint_sha256"],
        )
        runner = Engine("v39", device)
        try:
            report["device"] = runner.device_name
            if smoke:
                yy, xx = np.mgrid[:180, :240]
                pixels = np.stack([xx % 256, yy % 256, (xx + yy) % 256], -1).astype("uint8")
                source = destination.parent / "synthetic-source.png"
                Image.fromarray(pixels).save(source)
                items, errors = collect_inputs([source])
                assert not errors
                decoded, metadata, _ = read_image(items[0])
                output, record = runner.process(decoded)
                assert output.shape == pixels.shape and output.dtype == np.uint8
                for fmt in ("PNG", "JPEG"):
                    path = destination.parent / ("synthetic-result." + fmt.lower())
                    save_result(path, output, metadata, fmt)
                    with Image.open(path) as image:
                        assert image.size == (240, 180) and image.info["icc_profile"]
                report["decision"] = record["decision"]
            report["status"] = "PASS"
        finally:
            runner.close()
    except Exception:
        report["error"] = traceback.format_exc()
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    return report
