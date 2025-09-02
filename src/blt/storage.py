from pathlib import Path
from time import time
from typing import Iterable, List, Tuple
from io import BytesIO
from PIL import Image

from .supabase_client import get_supabase
from .config import settings

def _resize_to_jpeg_bytes(p: Path) -> bytes:
    """
    Redimensiona para lado máx settings.VISION_MAX_SIDE e exporta JPEG com qualidade definida.
    """
    img = Image.open(p).convert("RGB")
    w, h = img.size
    max_side = settings.VISION_MAX_SIDE
    if max(w, h) > max_side:
        img.thumbnail((max_side, max_side))  # mantém proporção
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=settings.VISION_JPEG_QUALITY, optimize=True)
    return buf.getvalue()

def upload_paths_get_signed_urls(paths: Iterable[Path], prefix: str, ttl_seconds: int) -> List[Tuple[str, str]]:
    """
    Sobe 'paths' para {prefix}/ no bucket e devolve lista de (key, signed_url).
    Usa redimensionamento para JPEG antes de enviar (menor custo/latência).
    """
    sb = get_supabase()
    bucket = settings.SUPABASE_BUCKET
    out: List[Tuple[str, str]] = []
    for i, p in enumerate(paths, start=1):
        key = f"{prefix}/{int(time())}_{i:02d}.jpg"  # normalizamos para .jpg
        data = _resize_to_jpeg_bytes(p)
        # upload (permitir overwrite via upsert header)
        sb.storage.from_(bucket).upload(
            key,
            data,
            {"content-type": "image/jpeg", "x-upsert": "true"}
        )
        # signed URL curto
        signed = sb.storage.from_(bucket).create_signed_url(key, ttl_seconds)
        url = signed.get("signedURL") or signed.get("signed_url") or signed.get("data", {}).get("signedUrl") or signed.get("data", {}).get("signedURL")
        out.append((key, url))
    return out

def delete_objects(keys: Iterable[str]) -> None:
    """
    Remove uma lista de keys do bucket.
    """
    sb = get_supabase()
    bucket = settings.SUPABASE_BUCKET
    sb.storage.from_(bucket).remove(list(keys))

# (mantém esta função opcional para guardar fotos do anúncio de forma persistente, se quiseres)
def upload_photos_and_get_urls(folder: Path, book_slug: str) -> list[str]:
    paths = sorted([p for p in folder.glob("*") if p.suffix.lower() in {".jpg",".jpeg",".png",".webp"}])
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
    return "application/octet-stream"
