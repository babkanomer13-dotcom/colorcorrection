"""Derive Windows icon sizes from the one approved application mark."""

import io
from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parents[1] / "assets"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def icon_bytes(logo):
    with Image.open(logo) as image:
        if image.mode != "RGBA" or image.width != image.height:
            raise ValueError("The application mark must be square RGBA")
        if image.getchannel("A").getextrema() != (0, 255):
            raise ValueError("The application mark must have transparent and solid pixels")
        output = io.BytesIO()
        image.save(output, format="ICO", sizes=[(n, n) for n in SIZES])
        return output.getvalue()


def validate_icon(path):
    """Never accidentally build the old icon from a previous QA directory."""
    expected = Image.open(io.BytesIO(icon_bytes(ASSETS / "logo.png")))
    try:
        with expected, Image.open(path) as actual:
            if actual.format != "ICO" or actual.ico.sizes() != expected.ico.sizes():
                raise ValueError("Wrong icon format or sizes")
            # PNG compression bytes may differ between the legacy and modern
            # Pillow/zlib versions. Compare every decoded RGBA frame instead.
            for size in expected.ico.sizes():
                if actual.ico.getimage(size).tobytes() != expected.ico.getimage(size).tobytes():
                    raise ValueError("Wrong icon pixels")
    except (OSError, ValueError) as exc:
        raise ValueError("Stale ColorPro icon: run python -m colorpro.build.brand_assets") from exc


def main():
    (ASSETS / "logo.ico").write_bytes(icon_bytes(ASSETS / "logo.png"))


if __name__ == "__main__":
    main()
