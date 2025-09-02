from pathlib import Path
from time import time
from .supabase_client import get_supabase
from .config import settings

def upload_photos_and_get_urls(folder: Path, book_slug: str) -> list[str]:
    """
    Sobe as fotos da pasta para o bucket e devolve URLs públicos.
    """
    sb = get_supabase()
    bucket = settings.SUPABASE_BUCKET
    urls: list[str] = []
    paths = sorted([p for p in folder.glob("*") if p.suffix.lower() in {".jpg",".jpeg",".png",".webp"}])
    for i, p in enumerate(paths, start=1):
        key = f"{book_slug}/{int(time())}_{i:02d}{p.suffix.lower()}"
        with p.open("rb") as f:
            sb.storage.from_(bucket).upload(key, f.read(), {"content-type": _guess_mime(p.suffix)})
        public_url = sb.storage.from_(bucket).get_public_url(key)
        urls.append(public_url)
    return urls

def _guess_mime(ext: str) -> str:
    ext = ext.lower()
    if ext in [".jpg", ".jpeg"]: return "image/jpeg"
    if ext == ".png": return "image/png"
    if ext == ".webp": return "image/webp"
    return "application/octet-stream"
