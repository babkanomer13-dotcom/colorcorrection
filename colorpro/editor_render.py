"""Bounded preview work; the same exact RGB8 operators also render exports."""

import numpy as np
from colorcorrection.levels_operator import apply_rgb_lut
from PySide6.QtGui import QImage

from colorpro.manual_hsl import apply_hsl
from colorpro.manual_tone import combined_lut


class PreviewCancelled(Exception):
    pass


def rgb_image(pixels):
    """Own the bytes before crossing threads. No PNG encode/decode round trip."""
    pixels = np.ascontiguousarray(pixels)
    height, width = pixels.shape[:2]
    return QImage(
        pixels.data, width, height, pixels.strides[0], QImage.Format.Format_RGB888
    ).copy()


class PreviewRenderer:
    """One cached LUT stage, used by a single worker at a time."""

    def __init__(self):
        self.source = self.lut_key = self.mapped = None

    def render(self, pixels, snapshot, enabled, cancelled=lambda: False):
        def checkpoint():
            if cancelled():
                raise PreviewCancelled()

        checkpoint()
        result = pixels
        if enabled:
            levels, tone, hsl, balance = snapshot
            lut = combined_lut(levels, tone, balance)
            key = lut.tobytes()
            if self.source is not pixels or self.lut_key != key:
                mapped = apply_rgb_lut(pixels, lut)
                checkpoint()
                self.source, self.lut_key, self.mapped = pixels, key, mapped
            result = apply_hsl(self.mapped, hsl, checkpoint=checkpoint)
        checkpoint()
        return rgb_image(result)
