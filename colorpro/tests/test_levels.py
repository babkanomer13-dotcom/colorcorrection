import numpy as np
import pytest
from PIL import Image, JpegImagePlugin

from colorpro.files import collect_inputs, output_name, output_path
from colorpro.levels import LevelsSession, defaults, levels_lut, picked_levels


def test_short_result_names_and_collisions(tmp_path):
    photos = []
    for folder in ("one", "two"):
        path = tmp_path / folder / "IMG_2362.JPG"
        path.parent.mkdir()
        Image.new("RGB", (20, 20), "gray").save(path)
        photos.append(collect_inputs([path])[0][0])
    assert output_name(photos[0], "JPEG") == "IMG_2362_с.jpg"
    assert output_name(photos[0], "PNG") == "IMG_2362_с.png"
    first = output_path(tmp_path / "results", photos[0], "JPEG")
    first.write_bytes(b"do not overwrite")
    second = output_path(tmp_path / "results", photos[1], "JPEG")
    assert first.name == second.name == "IMG_2362_с.jpg" and first.parent != second.parent
    assert first.read_bytes() == b"do not overwrite"


def test_lut_identity_channel_and_composition():
    from colorcorrection.auto_color import _gamma_bank
    from colorcorrection.levels_operator import Levels

    identity = np.broadcast_to(np.arange(256, dtype=np.uint8), (3, 256))
    settings = defaults()
    assert np.array_equal(levels_lut(settings), identity)
    settings[1]["gamma"] = 0.89
    lut = levels_lut(settings)
    assert np.array_equal(lut[0], _gamma_bank().lut(Levels(gamma=0.89)))
    assert np.array_equal(lut[1:], identity[1:])
    settings[0].update(input_black=8, input_white=239, output_black=3, output_white=244)
    composite = _gamma_bank().lut(Levels(**settings[0]))
    assert np.array_equal(levels_lut(settings), composite[lut])
    with pytest.raises(ValueError):
        settings[0]["input_white"] = 8
        levels_lut(settings)


def test_point_pickers_and_source_parameters_untouched():
    settings = defaults()
    for kind, expected in (("black", 0), ("white", 255)):
        picked = picked_levels(settings, [130, 150, 110], kind)
        lut = levels_lut(picked)
        assert [int(lut[c, value]) for c, value in enumerate([130, 150, 110])] == [expected] * 3
    lut = levels_lut(picked_levels(settings, [130, 150, 110], "gray"))
    assert max(abs(int(lut[c, value]) - 130) for c, value in enumerate([130, 150, 110])) <= 1
    assert settings == defaults()


@pytest.mark.parametrize("fmt,suffix", [("PNG", ".png"), ("JPEG", ".jpg")])
def test_manual_save_full_size_original_safe(tmp_path, fmt, suffix):
    from colorcorrection.levels_operator import apply_rgb_lut

    source = tmp_path / ("Андрей" + suffix)
    output = tmp_path / ("Андрей_с" + suffix)
    pixels = np.random.default_rng(17).integers(0, 255, (240, 360, 3), dtype=np.uint8)
    Image.fromarray(pixels).save(source)
    Image.fromarray(pixels).save(output)
    original = source.read_bytes()
    untouched = output.read_bytes()
    session = LevelsSession(output, source)
    session.save(defaults())
    assert output.read_bytes() == untouched
    settings = defaults()
    settings[0]["gamma"] = 1.21
    expected = apply_rgb_lut(session.pixels, levels_lut(settings))
    result = session.save(settings)
    assert result["manual_levels"] == settings and len(result["output_pixel_sha256"]) == 64
    assert source.read_bytes() == original
    with Image.open(output) as image:
        assert image.size == (360, 240) and image.info["icc_profile"]
        if fmt == "PNG":
            assert np.array_equal(np.asarray(image), expected)
        else:
            assert JpegImagePlugin.get_sampling(image) == 0
            assert all(v == 1 for table in image.quantization.values() for v in table)
    assert not list(tmp_path.glob(".colorpro-levels-*"))
    with pytest.raises(ValueError):
        session.save(settings)  # External/concurrent change is not overwritten.
    with pytest.raises(ValueError, match="исходник"):
        LevelsSession(source, source)


def test_atomic_manual_save_failure_preserves_file(tmp_path, monkeypatch):
    import colorpro.levels as levels

    source, output = tmp_path / "source.png", tmp_path / "output.png"
    Image.new("RGB", (20, 30), (120, 100, 90)).save(source)
    output.write_bytes(source.read_bytes())
    session = LevelsSession(output, source)
    before = output.read_bytes()

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(levels, "save_result", fail)
    settings = defaults()
    settings[0]["gamma"] = 1.25
    with pytest.raises(OSError, match="disk full"):
        session.save(settings)
    assert output.read_bytes() == before
    assert not list(tmp_path.glob(".colorpro-levels-*"))
