from pathlib import Path
import json, re
from typing import Optional, List

import requests
from openai import OpenAI

from .config import settings
from .storage import upload_paths_get_signed_urls, delete_objects
from .heic_convert import convert_folder as convert_heic_folder

ISBN_RE = re.compile(r"\b(?:97[89][-\s]?)?\d{1,5}[-\s]?\d{1,7}[-\s]?\d{1,7}[-\s]?[\dxX]\b")

def _select_images(folder: Path, max_images: int) -> List[Path]:
    IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
    imgs = [p for p in folder.glob("*") if p.suffix.lower() in IMG_EXTS]
    imgs.sort()  # 01, 02, ...
    if not imgs:
        raise FileNotFoundError(f"Sem imagens em {folder}. Coloca .jpg/.png/.heic e volta a tentar.")
    return imgs[:max_images]


def _image_parts_with_temp_urls(folder: Path) -> tuple[list[dict], list[str]]:
    """
    Sobe imagens ao Storage, cria signed URLs e devolve (image_parts, keys_subidas).
    O chamador é responsável por apagar as keys (cleanup).
    """
    paths = _select_images(folder, settings.VISION_MAX_IMAGES)
    prefix = f"{settings.VISION_UPLOAD_PREFIX}/{folder.name}"
    pairs = upload_paths_get_signed_urls(paths, prefix=prefix, ttl_seconds=settings.VISION_SIGNED_URL_TTL)
    image_parts = [{"type": "image_url", "image_url": {"url": url}} for (key, url) in pairs]
    keys = [key for (key, url) in pairs]
    return image_parts, keys

def _vision_extract(folder: Path) -> dict:
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    image_parts, keys = _image_parts_with_temp_urls(folder)
    try:
        prompt = (
            "Lê capa/contra-capa e devolve JSON com: "
            "title (string), author (string|null), isbn (string|null), genre (string|null). "
            "Se houver vários ISBNs, escolhe o mais completo (ISBN-13). Não inventes; se não vires, usa null."
        )
        msg = [{"role": "user", "content": [{"type": "text", "text": prompt}, *image_parts]}]
        resp = client.chat.completions.create(
            model=(settings.OPENAI_MODEL or "gpt-4o-mini"),
            messages=msg,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
        # fallback: tentar capturar ISBN por texto
        if not data.get("isbn"):
            text_pull = client.chat.completions.create(
                model=(settings.OPENAI_MODEL or "gpt-4o-mini"),
                messages=[{"role": "user", "content": [{"type": "text", "text": "Extrai texto bruto."}, *image_parts]}],
                temperature=0.0
            ).choices[0].message.content or ""
            m = ISBN_RE.search(text_pull.replace(" ", ""))
            if m:
                data["isbn"] = m.group(0)
        return {
            "title": (data.get("title") or "").strip(),
            "author": (data.get("author") or None),
            "isbn": (data.get("isbn") or None),
            "genre": (data.get("genre") or None),
        }
    finally:
        # apagar SEMPRE do Storage (mesmo se der erro)
        try:
            delete_objects(keys)
        except Exception:
            pass

def _google_books(isbn: str) -> Optional[dict]:
    try:
        r = requests.get("https://www.googleapis.com/books/v1/volumes", params={"q": f"isbn:{isbn}"}, timeout=10)
        r.raise_for_status()
        items = r.json().get("items") or []
        if not items: return None
        v = items[0]["volumeInfo"]
        return {
            "title": v.get("title"),
            "author": ", ".join(v.get("authors", [])) or None,
            "publisher": v.get("publisher"),
            "publishedDate": v.get("publishedDate"),
            "pageCount": v.get("pageCount"),
            "categories": ", ".join(v.get("categories", [])) or None,
            "language": v.get("language"),
        }
    except Exception:
        return None

def _compose_description_pt(meta: dict) -> str:
    base = [
        f"TÍTULO: {meta['title']}" if meta.get("title") else "TÍTULO: N/D",
    ]
    if meta.get("author"): base.append(f"Autor(es): {meta['author']}")
    if meta.get("isbn"): base.append(f"ISBN: {meta['isbn']}")
    base.append("")  # linha vazia
    base.append("Livro em bom estado.")
    base.append(f"Entrega em mão na {settings.VINTED_LOCATION}, senão {settings.VINTED_SHIPPING}.")
    base.append("Tenho outros livros à venda; ao comprar mais, paga apenas uma vez o transporte.")
    return "\n".join(base)

def _suggest_price(folder: Path) -> float:
    return round(max(settings.PRICE_MIN, 5) + settings.PRICE_MARGIN_EUR, 2)

def describe_book_from_folder(folder: Path) -> dict:
    # ⬇️ Convert any HEIC/HEIF in-place to JPEG before we proceed
    try:
        convert_heic_folder(folder, recursive=False, delete_src=True, quality=settings.VISION_JPEG_QUALITY)
    except Exception:
        pass
    vision = _vision_extract(folder)
    gb = _google_books(vision["isbn"]) if vision.get("isbn") else None

    title = (vision.get("title") or (gb.get("title") if gb else None) or folder.name.replace("_", " ").title()).strip()
    author = vision.get("author") or (gb.get("author") if gb else None)
    genre = vision.get("genre") or (gb.get("categories") if gb else None)
    isbn = vision.get("isbn")

    price = _suggest_price(folder)
    description_pt = _compose_description_pt({"title": title, "author": author, "isbn": isbn})

    return {
        "title": title,
        "author": author,
        "isbn": isbn,
        "genre": genre,
        "price": price,
        "description": description_pt,
    }
