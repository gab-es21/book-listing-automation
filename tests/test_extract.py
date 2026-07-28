from blt import extract
from blt.almedina_lookup import AlmedinaLookupError
from blt.isbnsearch_lookup import IsbnSearchLookupError


def _boom(*a, **k):
    raise AssertionError("this should not have been called")


def test_barcode_and_lookup_succeed(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: "9789896689704")
    monkeypatch.setattr(extract, "lookup_by_isbn", lambda isbn: {"title": "Sempre Tu", "author": "Colleen Hoover"})
    monkeypatch.setattr(extract, "isbnsearch_lookup_by_isbn", _boom)

    result = extract.extract_book_fields(tmp_path)

    assert result == {"title": "Sempre Tu", "author": "Colleen Hoover", "isbn": "9789896689704"}


def test_almedina_miss_falls_back_to_isbnsearch_and_succeeds(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: "9789898032577")
    monkeypatch.setattr(extract, "lookup_by_isbn", lambda isbn: None)
    monkeypatch.setattr(
        extract, "isbnsearch_lookup_by_isbn", lambda isbn: {"title": "A villa", "author": "Nora Roberts"}
    )

    result = extract.extract_book_fields(tmp_path)

    assert result == {"title": "A villa", "author": "Nora Roberts", "isbn": "9789898032577"}


def test_almedina_error_falls_back_to_isbnsearch_and_succeeds(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: "9789898032577")

    def raise_error(isbn):
        raise AlmedinaLookupError("blocked")

    monkeypatch.setattr(extract, "lookup_by_isbn", raise_error)
    monkeypatch.setattr(
        extract, "isbnsearch_lookup_by_isbn", lambda isbn: {"title": "A villa", "author": "Nora Roberts"}
    )

    result = extract.extract_book_fields(tmp_path)

    assert result == {"title": "A villa", "author": "Nora Roberts", "isbn": "9789898032577"}


def test_both_sources_miss_keeps_isbn_leaves_unresolved(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: "9789896689704")
    monkeypatch.setattr(extract, "lookup_by_isbn", lambda isbn: None)
    monkeypatch.setattr(extract, "isbnsearch_lookup_by_isbn", lambda isbn: None)

    result = extract.extract_book_fields(tmp_path)

    assert result == {"title": None, "author": None, "isbn": "9789896689704"}


def test_both_sources_error_keeps_isbn_leaves_unresolved(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: "9789896689704")

    def raise_almedina_error(isbn):
        raise AlmedinaLookupError("blocked")

    def raise_isbnsearch_error(isbn):
        raise IsbnSearchLookupError("blocked")

    monkeypatch.setattr(extract, "lookup_by_isbn", raise_almedina_error)
    monkeypatch.setattr(extract, "isbnsearch_lookup_by_isbn", raise_isbnsearch_error)

    result = extract.extract_book_fields(tmp_path)

    assert result == {"title": None, "author": None, "isbn": "9789896689704"}


def test_no_barcode_leaves_unresolved_no_lookup_attempted(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: None)
    monkeypatch.setattr(extract, "lookup_by_isbn", _boom)
    monkeypatch.setattr(extract, "isbnsearch_lookup_by_isbn", _boom)

    result = extract.extract_book_fields(tmp_path)

    assert result == {"title": None, "author": None, "isbn": None}
