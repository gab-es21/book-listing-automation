from pathlib import Path
from time import time
from typing import Iterable, List, Tuple
from io import BytesIO
from PIL import Image, UnidentifiedImageError

# Register HEIC opener (works with latest pillow-heif wheels)
try:
    from pillow_heif import register_heif_opener, open_heif
    register_heif_opener()
    _HAVE_HEIF = True
except Exception:
    open_heif = None  # type: ignore
    _HAVE_HEIF = False

from .supabase_client import get_supabase
from .config import settings
from .supabase_client import get_storage

IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}

def _load_image_any(p: Path) -> Image.Image:
    """
    Load image with robust HEIC support, selecting the PRIMARY image in multi-image HEICs.
    Pure Python: relies only on pillow-heif wheels (bundled libheif).
    """
    try:
        # Pillow uses the registered HEIC plugin when available
        return Image.open(p)
    except UnidentifiedImageError:
        # Explicit HEIC path via open_heif -> primary image
        if p.suffix.lower() in {".heic", ".heif"} and _HAVE_HEIF and open_heif is not None:
            hf = open_heif(
                str(p),
                convert_hdr_to_8bit=True,
                apply_transformations=True,
                load_truncated=True,
            )
            # HeifFile points to primary image; build a PIL Image from decoded bytes
            try:
                return hf.to_pillow()  # pillow-heif ≥0.17
            except AttributeError:
                return Image.frombytes(hf.mode, hf.size, hf.data, "raw", hf.mode, hf.stride)
        raise

def _resize_to_jpeg_bytes(p) -> bytes:
    """
    Redimensiona para lado máx settings.VISION_MAX_SIDE e exporta JPEG com qualidade definida.
    Garante RGB e remove metadata pesada.
    """
    img = Image.open(p).convert("RGB")
    w, h = img.size
    max_side = settings.VISION_MAX_SIDE
    if max(w, h) > max_side:
        if w >= h:
            nh = int(h * (max_side / w))
            img = img.resize((max_side, nh))
        else:
            nw = int(w * (max_side / h))
            img = img.resize((nw, max_side))

    out = BytesIO()
    img.save(out, "JPEG", quality=settings.VISION_JPEG_QUALITY, optimize=True)
    return out.getvalue()

def upload_paths_get_signed_urls(
    paths, prefix: str, ttl_seconds: int = 60
) -> List[Tuple[str, str]]:
    """
    Sobe 'paths' para {prefix}/ no bucket e devolve lista de (key, signed_url).
    Usa redimensionamento para JPEG antes de enviar (menor custo/latência).
    """
    storage = get_storage()
    bucket = settings.SUPABASE_BUCKET
    out: List[Tuple[str, str]] = []

    for i, p in enumerate(paths, start=1):
        key = f"{prefix}/{int(time())}_{i:02d}.jpg"  # normalizamos para .jpg
        data = _resize_to_jpeg_bytes(p)

        # upload (permitir overwrite via upsert header)
        storage.from_(bucket).upload(
            key,
            data,
            {"content-type": "image/jpeg", "x-upsert": "true"},
        )

        # signed URL (field name can vary between versions: signedURL | signed_url | signedUrl)
        signed = storage.from_(bucket).create_signed_url(key, ttl_seconds)
        url = signed.get("signedURL") or signed.get("signed_url") or signed.get("signedUrl")
        if url and not url.startswith("http"):
            # some versions return a path starting with /storage/...
            url = f"{settings.SUPABASE_URL}{url}"

        out.append((key, url))

    return out

def delete_objects(keys: Iterable[str]) -> None:
    sb = get_supabase()
    bucket = settings.SUPABASE_BUCKET
    sb.storage.from_(bucket).remove(list(keys))

def upload_photos_and_get_urls(folder: Path, book_slug: str) -> list[str]:
    paths = sorted([p for p in folder.glob("*") if p.suffix.lower() in IMG_EXTS])
    sb = get_supabase()
    bucket = settings.SUPABASE_BUCKET
    urls: list[str] = []
    for i, p in enumerate(paths, start=1):
        key = f"{book_slug}/{int(time())}_{i:02d}{p.suffix.lower()}"
        with p.open("rb") as f:
            sb.storage.from_(bucket).upload(key, f.read(), {"content-type": _guess_mime(p.suffix)})
        urls.append(sb.storage.from_(bucket).get_public_url(key))
    return urls

def _guess_mime(ext: str) -> str:
    ext = ext.lower()
    if ext in [".jpg", ".jpeg"]: return "image/jpeg"
    if ext == ".png": return "image/png"
    if ext == ".webp": return "image/webp"
    if ext in [".heic", ".heif"]: return "image/heic"
    return "application/octet-stream"

def delete_storage_keys(keys: List[str]) -> None:
    """Remove múltiplas chaves do Storage."""
    if not keys:
        return
    storage = get_storage()
    storage.from_(settings.SUPABASE_BUCKET).remove(keys)
