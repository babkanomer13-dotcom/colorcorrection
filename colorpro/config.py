"""Machine-local paths are deliberately excluded from the repository."""

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V39_SHA256 = "d5efdc7ab1e12e0a277e244331b32e4164c9be2836479db5782622f7b563bbe1"


def config_path():
    return Path(os.environ.get("COLORPRO_CONFIG", ROOT / "configs/local.colorpro.json"))


def load_config():
    bundle = (
        Path(sys._MEIPASS) / "payload"
        if getattr(sys, "frozen", False)
        else Path(os.environ["COLORPRO_BUNDLE"])
        if os.environ.get("COLORPRO_BUNDLE")
        else None
    )
    if bundle is not None:
        bundle = bundle.resolve()
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf8"))
        if (
            manifest.get("schema") != "colorpro-bundle-v1"
            or manifest.get("source_checkpoint_sha256") != V39_SHA256
        ):
            raise ValueError("Неверный комплект сохранённой V39")

        def local(name):
            path = (bundle / name).resolve()
            path.relative_to(bundle)  # Reject manifest paths outside the installed bundle.
            return str(path)

        product = "ColorProWin7" if manifest["platform"] == "win7" else "ColorPro"
        state = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / product
        return dict(
            checkpoint=local("weights/v39.pt"),
            checkpoint_sha256=manifest["files"]["weights/v39.pt"],
            source_checkpoint_sha256=V39_SHA256,
            detector=local("weights/yunet.onnx"),
            runtime_root=local("python"),
            state_root=str(state),
            protected_roots=[str(bundle), str(Path(sys.executable).parent)],
            bindings={local(name): digest for name, digest in manifest["files"].items()},
            platform=manifest["platform"],
        )
    path = config_path()
    if not path.is_file():
        raise RuntimeError("ColorPro ещё не настроен. Выполните colorpro.prepare_local.")
    config = json.loads(path.read_text(encoding="utf8"))
    if config.get("schema") != "colorpro-local-v39-v1":
        raise ValueError("Неверная конфигурация ColorPro")
    if config.get("checkpoint_sha256") != V39_SHA256 or not config.get("protected_roots"):
        raise ValueError("Нет защиты исходников или изменена версия V39")
    return config


def verify_runtime(config):
    if not config.get("bindings"):
        raise ValueError("Нет контрольных сумм runtime")
    for name, digest in config["bindings"].items():
        path = Path(name)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Компонент V39 отсутствует или изменён: {path.name}")
    model = Path(config["checkpoint"])
    if hashlib.sha256(model.read_bytes()).hexdigest() != config["checkpoint_sha256"]:
        raise ValueError("Контрольная сумма V39 не совпадает")
