from sqlalchemy import select

from blt import extract
from blt.models import Book


def _no_delay(monkeypatch):
    monkeypatch.setattr(extract.time, "sleep", lambda seconds: None)


def test_resolved_book_gets_filled_in_and_stays_pending(monkeypatch, temp_db):
    _no_delay(monkeypatch)
    with temp_db() as s:
        s.add(Book(folder_path="book_001", status="pending"))
        s.commit()

    monkeypatch.setattr(
        extract, "extract_book_fields",
        lambda folder: {"title": "Sempre Tu", "author": "Colleen Hoover", "isbn": "9789896689704"},
    )

    result = extract.extract_pending_books()

    assert result == {"resolved": 1, "failed": 0}
    with temp_db() as s:
        book = s.execute(select(Book)).scalar_one()
        assert book.title == "Sempre Tu"
        assert book.author == "Colleen Hoover"
        assert book.isbn == "9789896689704"
        assert book.description
        assert book.price == 7.0
        assert book.status == "pending"


def test_unresolved_book_marked_failed_keeps_isbn(monkeypatch, temp_db):
    _no_delay(monkeypatch)
    with temp_db() as s:
        s.add(Book(folder_path="book_002", status="pending"))
        s.commit()

    monkeypatch.setattr(
        extract, "extract_book_fields",
        lambda folder: {"title": None, "author": None, "isbn": "9789896689704"},
    )

    result = extract.extract_pending_books()

    assert result == {"resolved": 0, "failed": 1}
    with temp_db() as s:
        book = s.execute(select(Book)).scalar_one()
        assert book.title is None
        assert book.isbn == "9789896689704"
        assert book.status == "failed"


def test_rerun_does_not_reprocess_resolved_or_failed_rows(monkeypatch, temp_db):
    _no_delay(monkeypatch)
    with temp_db() as s:
        s.add(Book(folder_path="book_resolved", status="pending"))
        s.add(Book(folder_path="book_failed", status="pending"))
        s.commit()

    calls = []

    def fake_extract(folder):
        calls.append(str(folder))
        if "resolved" in str(folder):
            return {"title": "T", "author": "A", "isbn": "9789896689704"}
        return {"title": None, "author": None, "isbn": None}

    monkeypatch.setattr(extract, "extract_book_fields", fake_extract)

    first = extract.extract_pending_books()
    second = extract.extract_pending_books()

    assert first == {"resolved": 1, "failed": 1}
    assert second == {"resolved": 0, "failed": 0}
    assert len(calls) == 2  # not re-called on the second run


def test_limit_caps_how_many_books_are_processed(monkeypatch, temp_db):
    _no_delay(monkeypatch)
    with temp_db() as s:
        for i in range(3):
            s.add(Book(folder_path=f"book_{i}", status="pending"))
        s.commit()

    monkeypatch.setattr(
        extract, "extract_book_fields",
        lambda folder: {"title": "T", "author": "A", "isbn": "9789896689704"},
    )

    result = extract.extract_pending_books(limit=2)

    assert result == {"resolved": 2, "failed": 0}


def test_delay_happens_between_books_not_before_first_or_after_last(monkeypatch, temp_db):
    sleeps = []
    monkeypatch.setattr(extract.time, "sleep", lambda seconds: sleeps.append(seconds))
    with temp_db() as s:
        s.add(Book(folder_path="book_a", status="pending"))
        s.add(Book(folder_path="book_b", status="pending"))
        s.commit()

    monkeypatch.setattr(
        extract, "extract_book_fields",
        lambda folder: {"title": "T", "author": "A", "isbn": "9789896689704"},
    )

    extract.extract_pending_books()

    assert len(sleeps) == 1  # one gap between the two books, none before/after
