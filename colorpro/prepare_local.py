"""Create an immutable app runtime from the already approved local V39 assets."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from colorpro.config import ROOT, V39_SHA256, config_path

MODULES = (
    "__init__.py",
    "imageio.py",
    "auto_color.py",
    "auto_contrast.py",
    "auto_tone.py",
    "levels_operator.py",
    "classic_tool_policy.py",
    "classic_face_features.py",
    "classic_face_inference.py",
    "source_face_detector.py",
    "portrait_face_inputs.py",
    "models/__init__.py",
    "models/classic_face_controller.py",
    "models/classic_tool_controller.py",
    "models/adaptive_lut.py",
    "models/conditional_affine.py",
    "models/conditional_tone_affine.py",
    "models/conditional_pca_tone.py",
    "models/conditional_log_interval_tone.py",
    "assets/photoshop_centigamma_u8.npy",
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--release", default="v39-release1")
    parser.add_argument("--config-output", type=Path)
    args = parser.parse_args()
    private = args.private.resolve()
    archive = args.archive.resolve()
    state = private / "colorpro"
    if not args.release.replace("-", "").isalnum():
        raise ValueError("Invalid release name")
    runtime = state / "runtime" / args.release
    destination_config = args.config_output or config_path()
    if private.is_relative_to(archive):
        raise ValueError("Runtime must not be inside the archive")
    if runtime.exists() or destination_config.exists():
        raise FileExistsError("Existing ColorPro runtime/config is never overwritten")
    checkpoint = (
        private / "model-backups/v39-epoch005-raw-20260928-qualified-candidate/epoch-005.pt"
    )
    detector = private / "models/yunet-2023mar-8f2383e4/face_detection_yunet_2023mar.onnx"
    assert sha(checkpoint) == V39_SHA256
    assert sha(detector) == "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
    bindings = {}
    for src, dst in [
        (checkpoint, runtime / "weights/v39.pt"),
        (detector, runtime / "weights/yunet.onnx"),
    ] + [
        (ROOT / "src/colorcorrection" / name, runtime / "python/colorcorrection" / name)
        for name in MODULES
    ]:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        assert sha(src) == sha(dst)
        bindings[str(dst)] = sha(dst)
    config = dict(
        schema="colorpro-local-v39-v1",
        checkpoint=str(runtime / "weights/v39.pt"),
        checkpoint_sha256=V39_SHA256,
        detector=str(runtime / "weights/yunet.onnx"),
        runtime_root=str(runtime / "python"),
        state_root=str(state),
        protected_roots=[str(archive)],
        bindings=bindings,
    )
    with destination_config.open("x", encoding="utf8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    with (runtime / "preservation.json").open("x", encoding="utf8") as f:
        json.dump(
            dict(checkpoint_sha256=V39_SHA256, bindings=bindings, source_weights_modified=False),
            f,
            indent=2,
        )
    print(
        json.dumps(
            dict(runtime=str(runtime), config=str(destination_config), checkpoint_sha256=V39_SHA256)
        )
    )


if __name__ == "__main__":
    main()
