"""CC2014 RGB8 master Hue/Saturation/Lightness, independent of Photoshop."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import numpy as np

ASSET = Path(__file__).with_name("assets") / "cc2014_hsl.npz"


def hsl_defaults():
    return {"hue": 0, "saturation": 0, "lightness": 0}


def validate_hsl(settings):
    if not isinstance(settings, dict) or set(settings) != set(hsl_defaults()):
        raise ValueError("Неверные параметры цветового тона / насыщенности")
    for name, limit in (("hue", 180), ("saturation", 100), ("lightness", 100)):
        if type(settings[name]) is not int or not -limit <= settings[name] <= limit:
            raise ValueError(f"Параметр {name} вне диапазона")
    return settings


def hsl_available():
    return ASSET.is_file() and ASSET.with_suffix(".json").is_file()


@lru_cache(maxsize=1)
def load_hsl_bank():
    meta = json.loads(ASSET.with_suffix(".json").read_text(encoding="utf8"))
    if (
        meta.get("schema") != "cc2014-hsl-rgb8-v1"
        or meta.get("reference_version") != "15.0.0"
    ):
        raise ValueError("Непроверенная таблица цветового тона")
    if hashlib.sha256(ASSET.read_bytes()).hexdigest() != meta.get("sha256"):
        raise ValueError("Таблица цветового тона повреждена")
    with np.load(ASSET, allow_pickle=False) as archive:
        saturation, lightness = archive["saturation"], archive["lightness"]
    if saturation.dtype != np.uint8 or saturation.shape != (201, 32896, 2):
        raise ValueError("Неполная таблица насыщенности")
    if lightness.dtype != np.uint8 or lightness.shape != (201, 256):
        raise ValueError("Неполная таблица светлоты")
    high, low = np.tril_indices(256)
    if not np.array_equal(
        saturation[100], np.stack([low, high], axis=1)
    ) or not np.array_equal(lightness[100], np.arange(256)):
        raise ValueError("Неверная нейтральная точка цветового тона")
    saturation.flags.writeable = lightness.flags.writeable = False
    return saturation, lightness


def apply_hsl(pixels, settings, *, banks=None):
    """Master channel (not Colorize/range masks). Process bounded pixel chunks."""
    validate_hsl(settings)
    if (
        not isinstance(pixels, np.ndarray)
        or pixels.dtype != np.uint8
        or pixels.ndim != 3
        or pixels.shape[2] != 3
    ):
        raise ValueError("Цветовой тон поддерживает только RGB 8 бит")
    if not any(settings.values()):
        return pixels
    saturation, lightness = load_hsl_bank() if banks is None else banks
    source = pixels.reshape(-1, 3)
    result = np.empty_like(source)
    # Hue offset uses floor(x + .5), unlike the signed RGB sector division.
    shift = (settings["hue"] * 255 + 30) // 60
    sat = saturation[settings["saturation"] + 100]
    light = lightness[settings["lightness"] + 100]
    for start in range(0, len(source), 131072):
        values = light[source[start : start + 131072]].astype(np.int32)
        red, green, blue = values.T
        maximum, minimum = values.max(axis=1), values.min(axis=1)
        divisor = np.maximum(maximum - minimum, 1)
        numerator = np.where(
            maximum == red,
            green - blue,
            np.where(maximum == green, blue - red, red - green),
        )
        sector = np.where(maximum == red, 0, np.where(maximum == green, 2, 4))
        fraction = np.sign(numerator) * (
            (np.abs(numerator) * 510 + divisor) // (2 * divisor)
        )
        hue = (sector * 255 + fraction + shift) % 1530
        endpoints = sat[maximum * (maximum + 1) // 2 + minimum].astype(np.int32)
        minimum, maximum = endpoints.T
        delta = maximum - minimum
        sector, fraction = hue // 255, hue % 255
        position = np.where(sector % 2 == 0, fraction, 255 - fraction)
        middle = (delta * position + 127) // 256
        red = np.select(
            [sector == 0, sector == 1, sector == 4, sector == 5],
            [delta, middle, middle, delta],
            default=0,
        )
        green = np.select(
            [sector == 0, sector == 1, sector == 2, sector == 3],
            [middle, delta, delta, middle],
            default=0,
        )
        blue = np.select(
            [sector == 2, sector == 3, sector == 4, sector == 5],
            [middle, delta, delta, middle],
            default=0,
        )
        result[start : start + len(values)] = (
            np.stack([red, green, blue], axis=1) + minimum[:, None]
        )
    return result.reshape(pixels.shape)
