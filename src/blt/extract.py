"""
Barcode + Almedina lookup only - no vision/LLM fallback.

A photographed cover isn't a reliable enough source of truth for title and
author (small local models misread fine print often enough to matter), and
there is no acceptable alternative to a real, checksum-verified ISBN: once
`pyzbar` can't decode the barcode, or the decoded ISBN doesn't resolve to a
known title on Almedina, this gives up rather than guess - the book is left
unresolved for the human to fill in by hand.
"""
from pathlib import Path

from .almedina_lookup import AlmedinaLookupError, lookup_by_isbn
from .barcode import decode_isbn_barcode


def extract_book_fields(folder: Path) -> dict:
    """
    Returns {"title", "author", "isbn"}. `title` is None when the book could
    not be resolved (no barcode, or Almedina doesn't have it) - the caller
    marks that book status="failed" for manual entry. The barcode-decoded
    ISBN is kept even when unresolved, since it's still valid on its own.
    """
    folder = Path(folder)
    isbn = decode_isbn_barcode(folder / "isbn.jpg")
    if not isbn:
        return {"title": None, "author": None, "isbn": None}

    try:
        looked_up = lookup_by_isbn(isbn)
    except AlmedinaLookupError:
        looked_up = None

    if looked_up and looked_up.get("title"):
        return {"title": looked_up["title"], "author": looked_up.get("author"), "isbn": isbn}
    return {"title": None, "author": None, "isbn": isbn}
