"""
Barcode + Vinted (+ Almedina + isbnsearch.org fallbacks) lookup - no vision/LLM
fallback.

A photographed cover isn't a reliable enough source of truth for title and
author (small local models misread fine print often enough to matter), and
there is no acceptable alternative to a real, checksum-verified ISBN: once
`pyzbar` can't decode the barcode, or none of the lookups resolve the decoded
ISBN to a known title, this gives up rather than guess - the book is left
unresolved for the human to fill in by hand.

Lookup Priority:
1. Vinted (vinted.pt API) - Best autofill accuracy for platforms/listings.
2. Almedina (almedina.net) - Local Portuguese publisher/small-print fallback.
3. ISBNSearch (isbnsearch.org) - Global/international mass-market fallback.
"""
import random
import time
from pathlib import Path

from sqlalchemy import select

from . import db
from .almedina_lookup import AlmedinaLookupError
from .almedina_lookup import lookup_by_isbn as almedina_lookup_by_isbn
from .barcode import decode_isbn_barcode
from .config import settings
from .isbnsearch_lookup import IsbnSearchLookupError
from .isbnsearch_lookup import lookup_by_isbn as isbnsearch_lookup_by_isbn
from .listing import compose_listing
from .models import Book
from .vinted_lookup import VintedLookupError
from .vinted_lookup import lookup_by_isbn as vinted_lookup_by_isbn


def extract_book_fields(folder: Path) -> dict:
    """
    Returns {"title", "author", "isbn"}. `title` is None when the book could
    not be resolved (no barcode, or neither Vinted, Almedina, nor isbnsearch.org
    has it) - the caller marks that book status="failed" for manual entry. The
    barcode-decoded ISBN is kept even when unresolved, since it's still
    valid on its own.
    """
    folder = Path(folder)
    isbn = decode_isbn_barcode(folder / "isbn.jpg")
    if not isbn:
        return {"title": None, "author": None, "isbn": None}

    looked_up = None

    # 1. Primary Attempt: Vinted Internal API
    try:
        looked_up = vinted_lookup_by_isbn(isbn)
    except VintedLookupError:
        looked_up = None

    # 2. Secondary Attempt: Almedina (Portuguese market)
    if not (looked_up and looked_up.get("title")):
        try:
            looked_up = almedina_lookup_by_isbn(isbn)
        except AlmedinaLookupError:
            looked_up = None

    # 3. Tertiary Attempt: ISBNSearch.org (International / Mass-market)
    if not (looked_up and looked_up.get("title")):
        try:
            looked_up = isbnsearch_lookup_by_isbn(isbn)
        except IsbnSearchLookupError:
            looked_up = None

    # Return fields if any lookup succeeded in obtaining a title
    if looked_up and looked_up.get("title"):
        return {"title": looked_up["title"], "author": looked_up.get("author"), "isbn": isbn}

    return {"title": None, "author": None, "isbn": isbn}


def _extract_with_dev_cache(s, folder: Path) -> dict:
    """
    DEV_MODE only: if we already have a resolved title for this exact ISBN
    from an earlier real lookup (any book, any status), reuse it instead of
    hitting external endpoints again - repeated dev-mode runs over the
    same fixed test photos would otherwise burn rate limits re-resolving
    the same ISBNs. Genuinely new ISBNs still fall through to a real
    (paced) lookup chain.
    """
    folder = Path(folder)
    isbn = decode_isbn_barcode(folder / "isbn.jpg")
    if not isbn:
        return {"title": None, "author": None, "isbn": None}

    cached = s.execute(
        select(Book.title, Book.author).where(Book.isbn == isbn, Book.title.is_not(None)).limit(1)
    ).first()
    if cached:
        return {"title": cached.title, "author": cached.author, "isbn": isbn}

    return extract_book_fields(folder)


def extract_pending_books(limit: int | None = None) -> dict:
    """
    Runs extract_book_fields() over every Book row still status="pending"
    with no title yet: fills in title/author/isbn/description/price when
    resolved, or marks status="failed" (keeping the ISBN, if any) for manual
    entry when not. Commits after each book, so interrupting mid-run only
    loses the book in progress, and re-running only touches what's still
    status="pending" - already-failed rows are left alone. A small random
    delay between books keeps a multi-book run well under either lookup's
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

            if settings.DEV_MODE:
                fields = _extract_with_dev_cache(s, Path(book.folder_path))
            else:
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
