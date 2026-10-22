"""CC2014 RGB8 Color Balance expressed through the verified Levels operator."""

import math

import numpy as np


def balance_defaults():
    return {
        "shadows": [0, 0, 0],
        "midtones": [0, 0, 0],
        "highlights": [0, 0, 0],
        "preserve_luminosity": True,
    }


def validate_balance(settings):
    if not isinstance(settings, dict) or set(settings) != set(balance_defaults()):
        raise ValueError("Неверные параметры цветового баланса")
    if type(settings["preserve_luminosity"]) is not bool:
        raise ValueError("Неверный режим сохранения яркости")
    for name in ("shadows", "midtones", "highlights"):
        values = settings[name]
        if (
            not isinstance(values, (list, tuple))
            or len(values) != 3
            or any(type(v) is not int or not -100 <= v <= 100 for v in values)
        ):
            raise ValueError("Цветовой баланс: нужны три целых значения от −100 до 100")
    return settings


def balance_lut(settings):
    from colorcorrection.auto_color import _gamma_bank
    from colorcorrection.levels_operator import Levels

    validate_balance(settings)
    shadows, midtones, highlights = (
        settings[k] for k in ("shadows", "midtones", "highlights")
    )
    curves = []
    for channel in range(3):
        if settings["preserve_luminosity"]:
            black = max(shadows) - shadows[channel]
            white = 255 - highlights[channel] + min(highlights)
            exponent = midtones[channel] - int((max(midtones) + min(midtones)) / 2)
        else:
            black = max(0, -shadows[channel])
            white = min(255, 255 - highlights[channel])
            exponent = midtones[channel] + int(
                (shadows[channel] + highlights[channel]) / 2
            )
        gamma = math.floor(2.0 ** (exponent / 100.0) * 100 + 0.5) / 100
        if black >= white - 1:
            # CC2014 clamps crossed endpoints to a one-step interval.
            curve = np.where(np.arange(256) >= white, 255, 0).astype(np.uint8)
        else:
            curve = _gamma_bank().lut(
                Levels(input_black=black, input_white=white, gamma=gamma)
            )
        curves.append(curve)
    return np.stack(curves)
