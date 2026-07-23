"""
Combines every extraction technique into one priority-ordered pipeline:

1. Decode the ISBN barcode (deterministic, no LLM).
2. Look it up - Google Books first (broad coverage when its API is up),
   then Almedina (better coverage for Portuguese small-press/book-club
   editions Google Books often misses).
3. Only if the barcode is missing/unreadable, or neither lookup finds it,
   fall back to the local vision model reading the cover + the text-filter
   step. Even then, a barcode-decoded ISBN (if we have one) is kept over
   whatever the vision model guessed for it.
"""
from pathlib import Path

from .almedina_lookup import AlmedinaLookupError, lookup_by_isbn as almedina_lookup_by_isbn
from .barcode import decode_isbn_barcode
from .book_lookup import BookLookupError, lookup_by_isbn as google_lookup_by_isbn
from .filter import filter_book_fields
from .vision import extract_book_text


def _lookup_isbn_online(isbn: str) -> dict | None:
    try:
        result = google_lookup_by_isbn(isbn)
    except BookLookupError:
        result = None
    if result and result.get("title"):
        return result

    try:
        result = almedina_lookup_by_isbn(isbn)
    except AlmedinaLookupError:
        result = None
    if result and result.get("title"):
        return result

    return None


def extract_book_fields(folder: Path) -> dict:
    folder = Path(folder)
    isbn = decode_isbn_barcode(folder / "isbn.jpg")

    if isbn:
        looked_up = _lookup_isbn_online(isbn)
        if looked_up:
            return {"title": looked_up["title"], "author": looked_up.get("author"), "isbn": isbn}

    texts = extract_book_text(folder)
    fields = filter_book_fields(texts["cover_text"], texts["isbn_text"])
    if isbn:
        fields["isbn"] = isbn  # barcode decode beats the vision model's own ISBN guess
    return fields
