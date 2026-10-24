"""Manual, non-destructive-in-memory Levels using the verified CC2014 LUT bank."""

import copy
import hashlib
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

import numpy as np
from PIL import Image

from colorpro.files import collect_inputs, read_image, save_result
from colorpro.safety import validate_output_parent


def defaults():
    from colorcorrection.levels_operator import Levels

    return [asdict(Levels()) for _ in range(4)]


def levels_lut(settings):
    from colorcorrection.auto_color import _gamma_bank
    from colorcorrection.levels_operator import Levels

    if len(settings) != 4:
        raise ValueError("Нужны настройки RGB, R, G и B")
    bank = _gamma_bank()
    curves = [bank.lut(Levels(**row)) for row in settings]
    # Channel corrections followed by the composite RGB curve.
    return np.stack([curves[0][curve] for curve in curves[1:]])


def histogram(pixels):
    flat = pixels.reshape(-1, 3)
    result = np.zeros((3, 256), dtype=np.int64)
    for start in range(0, len(flat), 1_000_000):
        for channel in range(3):
            result[channel] += np.bincount(
                flat[start : start + 1_000_000, channel], minlength=256
            )
    return result


def picked_levels(settings, pixel, kind):
    """Set black/white anchors or neutralise the picked grey without global relighting."""
    from colorcorrection.auto_color import _gamma_bank
    from colorcorrection.levels_operator import Levels

    result = copy.deepcopy(settings)
    result[0] = defaults()[0]
    pixel = [int(value) for value in pixel]
    if kind not in {"black", "gray", "white"}:
        raise ValueError("Неизвестная пипетка")
    bank = _gamma_bank()
    target = round(
        sum(int(bank.lut(Levels(**result[c + 1]))[pixel[c]]) for c in range(3)) / 3
    )
    for channel, row in enumerate(result[1:]):
        value = pixel[channel]
        if kind == "black":
            row["input_black"] = min(value, row["input_white"] - 2)
        elif kind == "white":
            row["input_white"] = max(value, row["input_black"] + 2)
        else:
            # Prefer the least change among quantised gamma values with equal error.
            previous = row["gamma"]
            candidates = []
            for centigamma in range(10, 1000):
                row["gamma"] = centigamma / 100
                mapped = int(bank.lut(Levels(**row))[value])
                candidates.append(
                    (abs(mapped - target), abs(row["gamma"] - previous), centigamma)
                )
            row["gamma"] = min(candidates)[2] / 100
    return result


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            result.update(chunk)
    return result.hexdigest()


class LevelsSession:
    def __init__(self, output, source):
        if Path(output).is_symlink():
            raise ValueError(
                "Результат заменён символической ссылкой; сохранение запрещено"
            )
        self.path = Path(output).resolve()
        if self.path == Path(source).resolve():
            raise ValueError("Нельзя редактировать исходник вместо результата")
        validate_output_parent(self.path.parent)
        items, errors = collect_inputs([self.path])
        if errors or len(items) != 1:
            raise ValueError("Не удалось прочитать результат обработки")
        self.item = items[0]
        self.pixels, self.metadata, self.sha = read_image(self.item)
        self.pixels.flags.writeable = False
        self.histogram = histogram(self.pixels)
        image = Image.fromarray(self.pixels)
        image.thumbnail((1200, 1200))
        self.preview = np.array(image)
        image.close()
        self.format = "JPEG" if self.path.suffix.lower() in {".jpg", ".jpeg"} else "PNG"

    def render(self, snapshot):
        from colorcorrection.levels_operator import apply_rgb_lut
        from colorpro.manual_tone import combined_lut
        from colorpro.manual_hsl import apply_hsl

        levels, tone, hsl, balance = snapshot
        return apply_hsl(
            apply_rgb_lut(self.pixels, combined_lut(levels, tone, balance)), hsl
        )

    def save(self, settings, tone=None, hsl=None, balance=None):
        from colorcorrection.classic_face_inference import pixel_hash
        from colorcorrection.levels_operator import apply_rgb_lut

        self.item.unchanged()
        if digest(self.path) != self.sha:
            raise ValueError(
                "Результат изменён другой программой. Откройте его заново."
            )
        from colorpro.manual_tone import combined_lut

        lut = combined_lut(settings, tone, balance)
        result = apply_rgb_lut(self.pixels, lut)
        if hsl is not None:
            from colorpro.manual_hsl import apply_hsl

            result = apply_hsl(result, hsl)
        if not np.array_equal(result, self.pixels):
            with tempfile.TemporaryDirectory(
                prefix=".colorpro-levels-", dir=self.path.parent
            ) as temp:
                target = Path(temp) / ("result" + self.path.suffix)
                save_result(target, result, self.metadata, self.format)
                self.item.unchanged()
                if digest(self.path) != self.sha:
                    raise ValueError(
                        "Файл изменён во время сохранения; перезапись отменена."
                    )
                os.replace(target, self.path)
        data = {"manual_levels": settings, "output_pixel_sha256": pixel_hash(result)}
        if tone is not None:
            data["manual_brightness_contrast"] = dict(tone)
        if hsl is not None:
            data["manual_hsl"] = dict(hsl)
        if balance is not None:
            data["manual_color_balance"] = copy.deepcopy(balance)
        return data
