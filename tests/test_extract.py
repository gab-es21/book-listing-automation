from blt import extract
from blt.almedina_lookup import AlmedinaLookupError


def _boom(*a, **k):
    raise AssertionError("this should not have been called")


def test_barcode_and_lookup_succeed_skips_vision_entirely(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: "9789896689704")
    monkeypatch.setattr(extract, "lookup_by_isbn", lambda isbn: {"title": "Sempre Tu", "author": "Colleen Hoover"})
    monkeypatch.setattr(extract, "extract_book_text", _boom)
    monkeypatch.setattr(extract, "filter_book_fields", _boom)

    result = extract.extract_book_fields(tmp_path)

    assert result == {"title": "Sempre Tu", "author": "Colleen Hoover", "isbn": "9789896689704"}


def test_lookup_not_found_falls_back_but_keeps_barcode_isbn(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: "9789896689704")
    monkeypatch.setattr(extract, "lookup_by_isbn", lambda isbn: None)
    monkeypatch.setattr(extract, "extract_book_text", lambda folder: {"cover_text": "c", "isbn_text": "i"})
    monkeypatch.setattr(extract, "filter_book_fields", lambda cover_text, isbn_text: {"title": "T", "author": "A", "isbn": "wrong-guess"})

    result = extract.extract_book_fields(tmp_path)

    # barcode-decoded ISBN wins over whatever the vision/filter fallback guessed
    assert result == {"title": "T", "author": "A", "isbn": "9789896689704"}


def test_lookup_error_falls_back_but_keeps_barcode_isbn(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: "9789896689704")

    def raise_error(isbn):
        raise AlmedinaLookupError("blocked")

    monkeypatch.setattr(extract, "lookup_by_isbn", raise_error)
    monkeypatch.setattr(extract, "extract_book_text", lambda folder: {"cover_text": "c", "isbn_text": "i"})
    monkeypatch.setattr(extract, "filter_book_fields", lambda cover_text, isbn_text: {"title": "T", "author": "A", "isbn": None})

    result = extract.extract_book_fields(tmp_path)

    assert result == {"title": "T", "author": "A", "isbn": "9789896689704"}


def test_no_barcode_falls_back_entirely_no_lookup_attempted(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: None)
    monkeypatch.setattr(extract, "lookup_by_isbn", _boom)
    monkeypatch.setattr(extract, "extract_book_text", lambda folder: {"cover_text": "c", "isbn_text": "i"})
    monkeypatch.setattr(extract, "filter_book_fields", lambda cover_text, isbn_text: {"title": "T", "author": "A", "isbn": None})

    result = extract.extract_book_fields(tmp_path)

    assert result == {"title": "T", "author": "A", "isbn": None}
