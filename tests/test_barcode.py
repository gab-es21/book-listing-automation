from io import BytesIO

import barcode as barcode_lib
from barcode.writer import ImageWriter
from PIL import Image

from blt.barcode import decode_isbn_barcode


def _make_ean13_image(path, isbn12: str):
    """Renders a real EAN-13 barcode (check digit auto-computed) to a PNG file."""
    ean = barcode_lib.get("ean13", isbn12, writer=ImageWriter())
    buf = BytesIO()
    ean.write(buf, options={"write_text": False})
    buf.seek(0)
    Image.open(buf).save(path)


def test_decodes_a_valid_isbn_barcode(tmp_path):
    p = tmp_path / "isbn.png"
    _make_ean13_image(p, "978989710083")  # check digit auto-computed -> ...833

    assert decode_isbn_barcode(p) == "9789897100833"


def test_ignores_barcode_not_starting_978_or_979(tmp_path):
    p = tmp_path / "isbn.png"
    _make_ean13_image(p, "123456789012")  # valid EAN-13, but not an ISBN prefix

    assert decode_isbn_barcode(p) is None


def test_no_barcode_present_returns_none(tmp_path):
    p = tmp_path / "blank.png"
    Image.new("RGB", (100, 100), color="white").save(p)

    assert decode_isbn_barcode(p) is None
