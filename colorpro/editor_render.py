"""Bounded preview work; the same exact RGB8 operators also render exports."""

import numpy as np
from PIL import Image
from PySide6.QtGui import QImage

from colorpro.manual_hsl import apply_hsl
from colorpro.manual_tone import combined_lut


class PreviewCancelled(Exception):
    pass


def apply_rgb_lut(pixels, lut):
    """The same integer RGB lookup as export, without three NumPy gathers."""
    import cv2

    return cv2.LUT(pixels, np.ascontiguousarray(lut.T.reshape(256, 1, 3)))


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
        self.viewport_source = self.viewport_key = self.viewport_pixels = None

    def viewport(self, pixels, region, size, cancelled=lambda: False):
        """Cache screen-resolution input; cropping/resampling runs off the GUI."""
        key = region, size
        if self.viewport_source is pixels and self.viewport_key == key:
            return self.viewport_pixels
        if cancelled():
            raise PreviewCancelled()
        x0, y0, x1, y1 = region
        result = np.ascontiguousarray(pixels[y0:y1, x0:x1])
        if size != (x1 - x0, y1 - y0):
            with Image.fromarray(result) as image:
                resized = image.resize(size, Image.Resampling.LANCZOS)
                result = np.array(resized)
                resized.close()
        if cancelled():
            raise PreviewCancelled()
        self.viewport_source, self.viewport_key, self.viewport_pixels = (
            pixels,
            key,
            result,
        )
        return result

    def render(self, pixels, snapshot, enabled, cancelled=lambda: False):
        def checkpoint():
            if cancelled():
                raise PreviewCancelled()

        checkpoint()
        result = pixels
        if enabled:
            levels, tone, hsl, balance = snapshot[:4]
            lut = combined_lut(levels, tone, balance)
            key = lut.tobytes()
            if self.source is not pixels or self.lut_key != key:
                mapped = apply_rgb_lut(pixels, lut)
                checkpoint()
                self.source, self.lut_key, self.mapped = pixels, key, mapped
            result = apply_hsl(self.mapped, hsl, checkpoint=checkpoint)
        checkpoint()
        return rgb_image(result)
