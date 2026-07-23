"""
Barcode + Almedina lookup only - no vision/LLM fallback.

A photographed cover isn't a reliable enough source of truth for title and
author (small local models misread fine print often enough to matter), and
there is no acceptable alternative to a real, checksum-verified ISBN: once
`pyzbar` can't decode the barcode, or the decoded ISBN doesn't resolve to a
known title on Almedina, this gives up rather than guess - the book is left
unresolved for the human to fill in by hand.
"""
import random
import time
from pathlib import Path

from sqlalchemy import select

from . import db
from .almedina_lookup import AlmedinaLookupError, lookup_by_isbn
from .barcode import decode_isbn_barcode
from .listing import compose_listing
from .models import Book


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


def extract_pending_books(limit: int | None = None) -> dict:
    """
    Runs extract_book_fields() over every Book row still status="pending"
    with no title yet: fills in title/author/isbn/description/price when
    resolved, or marks status="failed" (keeping the ISBN, if any) for manual
    entry when not. Commits after each book, so interrupting mid-run only
    loses the book in progress, and re-running only touches what's still
    status="pending" - already-failed rows are left alone. A small random
    delay between books keeps a multi-book run well under Almedina's
    observed rate limit.
    """
    with db.SessionLocal() as s:
        query = select(Book).where(Book.status == "pending", Book.title.is_(None))
        if limit:
            query = query.limit(limit)
        books = s.execute(query).scalars().all()

        resolved = failed = 0
        for i, book in enumerate(books):
            if i > 0:
                time.sleep(random.uniform(2, 5))

            fields = extract_book_fields(Path(book.folder_path))
            if fields["title"]:
                listing = compose_listing(fields)
                book.title = listing["title"]
                book.author = listing["author"]
                book.isbn = listing["isbn"]
                book.description = listing["description"]
                book.price = listing["price"]
                resolved += 1
                print(f"[{book.folder_path}] resolvido: {book.title}")
            else:
                book.isbn = fields["isbn"]
                book.status = "failed"
                failed += 1
                print(f"[{book.folder_path}] nao foi possivel resolver - marcado como failed")
            s.commit()

        return {"resolved": resolved, "failed": failed}
