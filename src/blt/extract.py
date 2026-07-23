"""
Combines every extraction technique into one priority-ordered pipeline:

1. Decode the ISBN barcode (deterministic, no LLM).
2. Look it up on Almedina (a Portuguese bookstore's own site search - good
   coverage for small local-press/book-club editions).
3. Only if the barcode is missing/unreadable, or the lookup doesn't find it,
   fall back to the local vision model reading the cover + the text-filter
   step. Even then, a barcode-decoded ISBN (if we have one) is kept over
   whatever the vision model guessed for it.

Google Books was tried and dropped: its anonymous tier's daily quota was
easily exhausted, and even with a personal API key its isbn: query backend
had its own outage (503 on any numeric query, unrelated to anything on our
end) - too unreliable to depend on compared to barcode+Almedina, which
worked cleanly once set up correctly.
"""
from pathlib import Path

from .almedina_lookup import AlmedinaLookupError, lookup_by_isbn
from .barcode import decode_isbn_barcode
from .filter import filter_book_fields
from .vision import extract_book_text


def extract_book_fields(folder: Path) -> dict:
    folder = Path(folder)
    isbn = decode_isbn_barcode(folder / "isbn.jpg")

    if isbn:
        try:
            looked_up = lookup_by_isbn(isbn)
        except AlmedinaLookupError:
            looked_up = None
        if looked_up and looked_up.get("title"):
            return {"title": looked_up["title"], "author": looked_up.get("author"), "isbn": isbn}

    texts = extract_book_text(folder)
    fields = filter_book_fields(texts["cover_text"], texts["isbn_text"])
    if isbn:
        fields["isbn"] = isbn  # barcode decode beats the vision model's own ISBN guess
    return fields
