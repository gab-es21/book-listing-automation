from blt import extract
from blt.almedina_lookup import AlmedinaLookupError


def _boom(*a, **k):
    raise AssertionError("this should not have been called")


def test_barcode_and_lookup_succeed(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: "9789896689704")
    monkeypatch.setattr(extract, "lookup_by_isbn", lambda isbn: {"title": "Sempre Tu", "author": "Colleen Hoover"})

    result = extract.extract_book_fields(tmp_path)

    assert result == {"title": "Sempre Tu", "author": "Colleen Hoover", "isbn": "9789896689704"}


def test_barcode_found_but_not_on_almedina_keeps_isbn_leaves_unresolved(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: "9789896689704")
    monkeypatch.setattr(extract, "lookup_by_isbn", lambda isbn: None)

    result = extract.extract_book_fields(tmp_path)

    assert result == {"title": None, "author": None, "isbn": "9789896689704"}


def test_almedina_error_keeps_isbn_leaves_unresolved(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: "9789896689704")

    def raise_error(isbn):
        raise AlmedinaLookupError("blocked")

    monkeypatch.setattr(extract, "lookup_by_isbn", raise_error)

    result = extract.extract_book_fields(tmp_path)

    assert result == {"title": None, "author": None, "isbn": "9789896689704"}


def test_no_barcode_leaves_unresolved_no_lookup_attempted(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: None)
    monkeypatch.setattr(extract, "lookup_by_isbn", _boom)

    result = extract.extract_book_fields(tmp_path)

    assert result == {"title": None, "author": None, "isbn": None}
