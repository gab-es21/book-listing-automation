"""
Deterministic ISBN barcode decoding (EAN-13) - no LLM guessing involved.

A book's ISBN barcode is a standard EAN-13 barcode. A successful zbar decode
already includes checksum validation as part of the barcode standard itself,
so this is far more reliable than asking a vision model to transcribe the
tiny printed digits - confirmed in practice: it correctly decoded all 3 real
test books, each different from (and correcting) what the vision model had
misread.
"""
from pathlib import Path

from pyzbar.pyzbar import decode as zbar_decode

from .images import load_image_any


def decode_isbn_barcode(path: Path) -> str | None:
    """Reads an EAN-13 barcode starting 978/979 from a photo, else None."""
    img = load_image_any(path).convert("L")  # grayscale improves detection reliability
    for barcode in zbar_decode(img):
        if barcode.type != "EAN13":
            continue
        digits = barcode.data.decode("ascii")
        if len(digits) == 13 and digits[:3] in ("978", "979"):
            return digits
    return None
