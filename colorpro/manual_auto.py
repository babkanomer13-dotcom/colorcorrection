"""Expose already verified CC2014 auto tools to manual editing, without a model."""

from dataclasses import asdict

from colorpro.levels import defaults


def auto_settings(pixels, mode):
    from colorcorrection.auto_color import auto_color_parameters
    from colorcorrection.auto_contrast import auto_contrast_endpoints, rgb_histogram
    from colorcorrection.auto_tone import auto_tone_endpoints

    settings = defaults()
    if mode == 0:
        return [settings[0]] + [
            asdict(row) for row in auto_color_parameters(pixels).channels
        ]
    hist = rgb_histogram(pixels)
    if mode == 1:
        blacks, whites = auto_tone_endpoints(hist)
        for index, row in enumerate(settings[1:]):
            row.update(input_black=int(blacks[index]), input_white=int(whites[index]))
    elif mode == 2:
        black, white = auto_contrast_endpoints(hist)
        if white <= black:
            return settings
        settings[0].update(input_black=int(black), input_white=int(white))
    else:
        raise ValueError("Неизвестный автоинструмент")
    return settings
