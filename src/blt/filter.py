"""
Turns vision.py's raw OCR-ish text into clean, DB-ready fields.

ISBN uses plain regex validation - no model call, since a rigid, well-known
format like an ISBN is more reliably extracted deterministically than by
asking an LLM to "extract" it (which risks it subtly altering digits).
Title/author genuinely need language understanding (telling the title apart
from the author's name and other cover noise), so that part uses a small
local text model.
"""
import json
import re

import requests

from .config import settings

# A run of 10-25 digits/hyphens, anchored to digits at both ends (so it
# doesn't start/end mid-hyphen). Loose on purpose - length/prefix are
# validated afterwards on the digits alone.
_ISBN_CANDIDATE_RE = re.compile(r"\d[\d\-]{8,25}\d")


class FilterError(RuntimeError):
    pass


def _isbn13_checksum_ok(digits: str) -> bool:
    """
    ISBN-13 check digit: alternating weights 1,3 over the first 12 digits.
    Catches single-digit OCR misreads that still happen to have the right
    length/prefix (observed in practice: a misread digit transposition passed
    the length/prefix check but failed this checksum).
    """
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits[:12]))
    return (10 - total % 10) % 10 == int(digits[12])


def extract_isbn(raw_text: str) -> str | None:
    """Finds a valid 13-digit ISBN (starts 978/979, correct check digit) in raw OCR text, else None."""
    if not raw_text:
        return None
    for match in _ISBN_CANDIDATE_RE.finditer(raw_text):
        digits = re.sub(r"\D", "", match.group())
        if len(digits) == 13 and digits[:3] in ("978", "979") and _isbn13_checksum_ok(digits):
            return digits
    return None


_TITLE_AUTHOR_PROMPT = """Here is raw OCR text transcribed from a book's front cover:

{cover_text}

Identify the book title and author from this text, if clearly present. Rules: \
only use text that literally appears above, word for word - never invent or add \
words that are not present. A review quote, tagline, or slogan (often in quotes \
or all-caps, praising the book) is NOT the title. A newspaper/magazine name is \
NOT the author. A publisher name is neither. If you cannot find a clear title or \
author literally in the text, use null for that field - never guess or \
reconstruct one. Respond with JSON only: {{"title": string or null, "author": string or null}}."""


def extract_title_author(cover_text: str) -> dict:
    prompt = _TITLE_AUTHOR_PROMPT.format(cover_text=cover_text)
    try:
        r = requests.post(
            f"{settings.OLLAMA_HOST}/api/generate",
            json={
                "model": settings.OLLAMA_FILTER_MODEL,
                "prompt": prompt,
                "format": "json",
                "stream": False,
            },
            timeout=60,
        )
    except requests.RequestException as e:
        raise FilterError(
            f"Não foi possível contactar o Ollama em {settings.OLLAMA_HOST} ({e})."
        )
    if r.status_code >= 400:
        raise FilterError(f"Ollama devolveu erro {r.status_code}: {r.text[:300]}")
    try:
        data = json.loads(r.json()["response"])
    except (KeyError, ValueError) as e:
        raise FilterError(f"Resposta inesperada do Ollama: {e} - {r.text[:300]}")
    return {"title": data.get("title") or None, "author": data.get("author") or None}


def filter_book_fields(cover_text: str, isbn_text: str) -> dict:
    """Combines both into the clean shape the Book model needs."""
    fields = extract_title_author(cover_text)
    fields["isbn"] = extract_isbn(isbn_text)
    return fields
