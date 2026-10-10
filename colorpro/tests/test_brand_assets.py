import io

import pytest
from PIL import Image

from colorpro.build.brand_assets import ASSETS, SIZES, icon_bytes, validate_icon


def test_packaged_icon_is_derived_from_current_mark():
    validate_icon(ASSETS / "logo.ico")
    with Image.open(io.BytesIO(icon_bytes(ASSETS / "logo.png"))) as icon:
        assert icon.format == "ICO"
        assert icon.ico.sizes() == {(n, n) for n in SIZES}
        for size in SIZES:
            frame = icon.ico.getimage((size, size))
            assert frame.mode == "RGBA"
            assert frame.getpixel((0, 0))[3] == 0
            # Small icon antialiasing can contribute a few alpha units from
            # the nearby inner contour; the hole must remain visually clear.
            assert frame.getpixel((size // 2, size // 2))[3] <= 8


def test_stale_icon_is_rejected(tmp_path):
    stale = tmp_path / "old.ico"
    stale.write_bytes(b"old artwork")
    with pytest.raises(ValueError, match="Stale"):
        validate_icon(stale)
