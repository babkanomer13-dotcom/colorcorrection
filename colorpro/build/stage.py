"""Build inputs from an explicit allowlist. No photographs, private paths or research state."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from colorpro.config import ROOT, V39_SHA256, load_config, verify_runtime

APP = [
    "__init__.py",
    "config.py",
    "safety.py",
    "engine.py",
    "files.py",
    "batch.py",
    "preview.py",
    "ui.py",
    "widgets.py",
    "launcher.py",
    "diagnostics.py",
    "updates.py",
    "update_dialog.py",
]
RUNTIME = [
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
    "models/classic_face_controller.py",
    "models/classic_tool_controller.py",
    "assets/photoshop_centigamma_u8.npy",
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--platform", choices=("win10", "win7"), required=True)
    parser.add_argument("--icon", type=Path, required=True)
    args = parser.parse_args()
    config = load_config()
    verify_runtime(config)
    stage = args.output.resolve()
    stage.mkdir(parents=True, exist_ok=False)
    legacy = args.platform == "win7"
    for name in APP:
        text = (ROOT / "colorpro" / name).read_text(encoding="utf8")
        if legacy:
            text = text.replace("PySide6", "PySide2").replace(".position()", ".localPos()")
            text = text.replace(".exec()", ".exec_()")
            if name == "ui.py":
                text = text.replace("    QShortcut,\n", "")
                text = text.replace(
                    "    QAbstractItemView,\n", "    QAbstractItemView,\n    QShortcut,\n"
                )
                text = text.replace(
                    'QSettings("ColorPro", "Desktop")', 'QSettings("ColorProWin7", "Desktop")'
                )
                text = text.replace(
                    'self.device.addItem("Видеокарта · NVIDIA CUDA", "cuda")',
                    "# Legacy build has CPU-only PyTorch.",
                )
                text = text.replace('"Автоматически · GPU / CPU"', '"Автоматически · CPU"')
                text = text.replace(
                    '"AMD / Intel пока работают через CPU. Обучение здесь не запускается."',
                    '"Сборка Windows 7 работает на CPU. Обучение здесь не запускается."',
                )
        out = stage / "colorpro" / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf8")
    payload = stage / "payload"
    origin = Path(config["runtime_root"]) / "colorcorrection"
    changes = {}
    for name in RUNTIME:
        out = payload / "python/colorcorrection" / name
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin / name, out)
        if legacy and name == "auto_color.py":
            text = out.read_text(encoding="utf8").replace(
                "from importlib.resources import files", "from importlib_resources import files"
            )
            out.write_text(text, encoding="utf8")
            changes[name] = dict(
                original_sha256=sha(origin / name),
                packaged_sha256=sha(out),
                reason="Python 3.8 importlib.resources backport only",
            )
    # Package initializer originally imports unrelated train-time model families
    # using Python >=3.10. Inference needs only the two explicit V39 modules.
    init = payload / "python/colorcorrection/models/__init__.py"
    init.write_text(
        '"""Preserved V39 inference models only; no training registry."""\n', encoding="utf8"
    )
    changes["models/__init__.py"] = dict(
        original_sha256=sha(origin / "models/__init__.py"),
        packaged_sha256=sha(init),
        reason="Omit unrelated training registry",
    )
    (payload / "weights").mkdir()
    import torch

    saved = torch.load(config["checkpoint"], map_location="cpu", weights_only=True)
    checkpoint = payload / "weights/v39.pt"
    torch.save(dict(schema=saved["schema"], model_state_dict=saved["model_state_dict"]), checkpoint)
    packed = torch.load(checkpoint, map_location="cpu", weights_only=True)
    assert packed["model_state_dict"].keys() == saved["model_state_dict"].keys()
    assert all(
        torch.equal(tensor, packed["model_state_dict"][key])
        for key, tensor in saved["model_state_dict"].items()
    )
    shutil.copyfile(config["detector"], payload / "weights/yunet.onnx")
    files = {
        str(p.relative_to(payload)).replace("\\", "/"): sha(p)
        for p in payload.rglob("*")
        if p.is_file()
    }
    manifest = dict(
        schema="colorpro-bundle-v1",
        platform=args.platform,
        source_checkpoint_sha256=V39_SHA256,
        files=files,
        raw_model_tensors_identical=True,
        excluded=["ema", "optimizer", "rng", "training reports"],
        code_adaptations=changes,
    )
    (payload / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf8")
    shutil.copyfile(args.icon, stage / "colorpro.ico")
    for name in ("README-SETUP.txt", "README-WIN7.txt", "THIRD_PARTY_NOTICES.txt"):
        shutil.copyfile(ROOT / "colorpro/build" / name, stage / name)
    print(
        json.dumps(
            dict(
                stage=str(stage),
                platform=args.platform,
                files=len(files),
                checkpoint=sha(checkpoint),
                weights_unchanged=True,
            )
        )
    )


if __name__ == "__main__":
    main()
