from blt import extract
from blt.almedina_lookup import AlmedinaLookupError
from blt.isbnsearch_lookup import IsbnSearchLookupError
from blt.vinted_lookup import VintedLookupError


def _boom(*a, **k):
    raise AssertionError("this should not have been called")


def test_vinted_succeeds_no_fallback_needed(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: "9789896689704")
    monkeypatch.setattr(
        extract, "vinted_lookup_by_isbn", lambda isbn: {"title": "Sempre Tu", "author": "Colleen Hoover"}
    )
    monkeypatch.setattr(extract, "almedina_lookup_by_isbn", _boom)
    monkeypatch.setattr(extract, "isbnsearch_lookup_by_isbn", _boom)

    result = extract.extract_book_fields(tmp_path)

    assert result == {"title": "Sempre Tu", "author": "Colleen Hoover", "isbn": "9789896689704"}


def test_vinted_miss_falls_back_to_almedina_and_succeeds(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: "9789896689704")
    monkeypatch.setattr(extract, "vinted_lookup_by_isbn", lambda isbn: None)
    monkeypatch.setattr(
        extract, "almedina_lookup_by_isbn", lambda isbn: {"title": "Sempre Tu", "author": "Colleen Hoover"}
    )
    monkeypatch.setattr(extract, "isbnsearch_lookup_by_isbn", _boom)

    result = extract.extract_book_fields(tmp_path)

    assert result == {"title": "Sempre Tu", "author": "Colleen Hoover", "isbn": "9789896689704"}


def test_vinted_error_falls_back_to_almedina_and_succeeds(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: "9789896689704")

    def raise_error(isbn):
        raise VintedLookupError("blocked")

    monkeypatch.setattr(extract, "vinted_lookup_by_isbn", raise_error)
    monkeypatch.setattr(
        extract, "almedina_lookup_by_isbn", lambda isbn: {"title": "Sempre Tu", "author": "Colleen Hoover"}
    )
    monkeypatch.setattr(extract, "isbnsearch_lookup_by_isbn", _boom)

    result = extract.extract_book_fields(tmp_path)

    assert result == {"title": "Sempre Tu", "author": "Colleen Hoover", "isbn": "9789896689704"}


def test_vinted_and_almedina_miss_falls_back_to_isbnsearch_and_succeeds(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: "9789898032577")
    monkeypatch.setattr(extract, "vinted_lookup_by_isbn", lambda isbn: None)
    monkeypatch.setattr(extract, "almedina_lookup_by_isbn", lambda isbn: None)
    monkeypatch.setattr(
        extract, "isbnsearch_lookup_by_isbn", lambda isbn: {"title": "A villa", "author": "Nora Roberts"}
    )

    result = extract.extract_book_fields(tmp_path)

    assert result == {"title": "A villa", "author": "Nora Roberts", "isbn": "9789898032577"}


def test_vinted_and_almedina_error_falls_back_to_isbnsearch_and_succeeds(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: "9789898032577")

    def raise_vinted_error(isbn):
        raise VintedLookupError("blocked")

    def raise_almedina_error(isbn):
        raise AlmedinaLookupError("blocked")

    monkeypatch.setattr(extract, "vinted_lookup_by_isbn", raise_vinted_error)
    monkeypatch.setattr(extract, "almedina_lookup_by_isbn", raise_almedina_error)
    monkeypatch.setattr(
        extract, "isbnsearch_lookup_by_isbn", lambda isbn: {"title": "A villa", "author": "Nora Roberts"}
    )

    result = extract.extract_book_fields(tmp_path)

    assert result == {"title": "A villa", "author": "Nora Roberts", "isbn": "9789898032577"}


def test_all_sources_miss_keeps_isbn_leaves_unresolved(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: "9789896689704")
    monkeypatch.setattr(extract, "vinted_lookup_by_isbn", lambda isbn: None)
    monkeypatch.setattr(extract, "almedina_lookup_by_isbn", lambda isbn: None)
    monkeypatch.setattr(extract, "isbnsearch_lookup_by_isbn", lambda isbn: None)

    result = extract.extract_book_fields(tmp_path)

    assert result == {"title": None, "author": None, "isbn": "9789896689704"}


def test_all_sources_error_keeps_isbn_leaves_unresolved(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: "9789896689704")

    def raise_vinted_error(isbn):
        raise VintedLookupError("blocked")

    def raise_almedina_error(isbn):
        raise AlmedinaLookupError("blocked")

    def raise_isbnsearch_error(isbn):
        raise IsbnSearchLookupError("blocked")

    monkeypatch.setattr(extract, "vinted_lookup_by_isbn", raise_vinted_error)
    monkeypatch.setattr(extract, "almedina_lookup_by_isbn", raise_almedina_error)
    monkeypatch.setattr(extract, "isbnsearch_lookup_by_isbn", raise_isbnsearch_error)

    result = extract.extract_book_fields(tmp_path)

    assert result == {"title": None, "author": None, "isbn": "9789896689704"}


def test_vinted_title_only_falls_back_to_almedina_for_author(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: "9789896689704")
    monkeypatch.setattr(extract, "vinted_lookup_by_isbn", lambda isbn: {"title": "Sempre Tu", "author": None})
    monkeypatch.setattr(
        extract, "almedina_lookup_by_isbn", lambda isbn: {"title": "Wrong Title", "author": "Colleen Hoover"}
    )
    monkeypatch.setattr(extract, "isbnsearch_lookup_by_isbn", _boom)

    result = extract.extract_book_fields(tmp_path)

    # Title from Vinted is kept - Almedina only fills the missing author, never overwrites.
    assert result == {"title": "Sempre Tu", "author": "Colleen Hoover", "isbn": "9789896689704"}


def test_vinted_author_only_falls_back_to_almedina_for_title(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: "9789896689704")
    monkeypatch.setattr(
        extract, "vinted_lookup_by_isbn", lambda isbn: {"title": None, "author": "Colleen Hoover"}
    )
    monkeypatch.setattr(
        extract, "almedina_lookup_by_isbn", lambda isbn: {"title": "Sempre Tu", "author": "Wrong Author"}
    )
    monkeypatch.setattr(extract, "isbnsearch_lookup_by_isbn", _boom)

    result = extract.extract_book_fields(tmp_path)

    assert result == {"title": "Sempre Tu", "author": "Colleen Hoover", "isbn": "9789896689704"}


def test_partial_fields_from_all_three_sources_merge_together(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: "9789898032577")
    monkeypatch.setattr(extract, "vinted_lookup_by_isbn", lambda isbn: {"title": None, "author": None})
    monkeypatch.setattr(
        extract, "almedina_lookup_by_isbn", lambda isbn: {"title": "A villa", "author": None}
    )
    monkeypatch.setattr(
        extract, "isbnsearch_lookup_by_isbn", lambda isbn: {"title": "Wrong Title", "author": "Nora Roberts"}
    )

    result = extract.extract_book_fields(tmp_path)

    assert result == {"title": "A villa", "author": "Nora Roberts", "isbn": "9789898032577"}


def test_author_found_but_no_title_anywhere_still_unresolved(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: "9789896689704")
    monkeypatch.setattr(
        extract, "vinted_lookup_by_isbn", lambda isbn: {"title": None, "author": "Colleen Hoover"}
    )
    monkeypatch.setattr(extract, "almedina_lookup_by_isbn", lambda isbn: None)
    monkeypatch.setattr(extract, "isbnsearch_lookup_by_isbn", lambda isbn: None)

    result = extract.extract_book_fields(tmp_path)

    # Author alone doesn't count as resolved - caller marks status="failed" on missing title.
    assert result == {"title": None, "author": "Colleen Hoover", "isbn": "9789896689704"}


def test_no_barcode_leaves_unresolved_no_lookup_attempted(monkeypatch, tmp_path):
    monkeypatch.setattr(extract, "decode_isbn_barcode", lambda p: None)
    monkeypatch.setattr(extract, "vinted_lookup_by_isbn", _boom)
    monkeypatch.setattr(extract, "almedina_lookup_by_isbn", _boom)
    monkeypatch.setattr(extract, "isbnsearch_lookup_by_isbn", _boom)

    result = extract.extract_book_fields(tmp_path)

    assert result == {"title": None, "author": None, "isbn": None}
