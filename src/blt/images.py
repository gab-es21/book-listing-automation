from pathlib import Path

from PIL import Image, UnidentifiedImageError

try:
    from pillow_heif import register_heif_opener, open_heif
    register_heif_opener()
    _HAVE_HEIF = True
except Exception:
    open_heif = None  # type: ignore
    _HAVE_HEIF = False

IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}


def load_image_any(p: Path) -> Image.Image:
    """
    Load image with robust HEIC support, selecting the PRIMARY image in multi-image HEICs.
    Pure Python: relies only on pillow-heif wheels (bundled libheif).
    """
    try:
        return Image.open(p)
    except UnidentifiedImageError:
        if p.suffix.lower() in {".heic", ".heif"} and _HAVE_HEIF and open_heif is not None:
            hf = open_heif(
                str(p),
                convert_hdr_to_8bit=True,
                apply_transformations=True,
                load_truncated=True,
            )
            try:
                return hf.to_pillow()  # pillow-heif >= 0.17
            except AttributeError:
                return Image.frombytes(hf.mode, hf.size, hf.data, "raw", hf.mode, hf.stride)
        raise
