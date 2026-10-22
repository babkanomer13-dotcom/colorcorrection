"""Standalone CC2014 joint Brightness/Contrast maps. No Photoshop at runtime."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import numpy as np

ASSET = Path(__file__).with_name("assets") / "cc2014_brightness_contrast.npz"


def tone_defaults():
    return {"brightness": 0, "contrast": 0}


def validate_tone(settings):
    if not isinstance(settings, dict) or set(settings) != {"brightness", "contrast"}:
        raise ValueError("Неверные параметры яркости/контраста")
    for name, low, high in (("brightness", -150, 150), ("contrast", -50, 100)):
        value = settings[name]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"Параметр {name} вне диапазона")
    return settings


@lru_cache(maxsize=1)
def load_tone_bank():
    metadata = json.loads(ASSET.with_suffix(".json").read_text(encoding="utf8"))
    if (
        metadata.get("schema") != "cc2014-brightness-contrast-rgb8-v1"
        or metadata.get("reference_version") != "15.0.0"
    ):
        raise ValueError("Непроверенная таблица яркости/контраста")
    raw = ASSET.read_bytes()
    if hashlib.sha256(raw).hexdigest() != metadata.get("sha256"):
        raise ValueError("Таблица яркости/контраста повреждена")
    with np.load(ASSET, allow_pickle=False) as archive:
        bank = archive["lut"]
    if bank.dtype != np.uint8 or bank.shape != (301, 151, 256):
        raise ValueError("Неполная таблица яркости/контраста")
    if not np.array_equal(bank[150, 50], np.arange(256, dtype=np.uint8)):
        raise ValueError("Неверная нейтральная точка яркости/контраста")
    bank.flags.writeable = False
    return bank


def tone_available():
    return ASSET.is_file() and ASSET.with_suffix(".json").is_file()


def brightness_contrast_lut(settings):
    validate_tone(settings)
    brightness, contrast = settings["brightness"], settings["contrast"]
    if brightness == contrast == 0:
        return np.arange(256, dtype=np.uint8)
    return load_tone_bank()[brightness + 150, contrast + 50]


def combined_lut(levels, tone=None, balance=None):
    from colorpro.levels import levels_lut

    lut = levels_lut(levels)
    if tone is not None:
        lut = brightness_contrast_lut(tone)[lut]
    if balance is not None:
        from colorpro.manual_balance import balance_lut

        lut = np.take_along_axis(balance_lut(balance), lut, axis=1)
    return lut
