import pytest
import requests

from blt import filter as bf  # "filter" shadows a builtin, alias for clarity


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text or str(json_data)

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


# ---------------------------- extract_isbn ---------------------------- #
# Real OCR text captured earlier from the 3 books in this project.

def test_no_isbn_present_returns_none():
    text = '"Ainda mais provocador e intrigante do que Pássaros Feridos."\nWASHINGTON POST'
    assert bf.extract_isbn(text) is None


def test_malformed_12_digit_isbn_is_rejected():
    text = "ISBN 978-88-8228-36-9\nRomance Traduzido"
    assert bf.extract_isbn(text) is None


def test_valid_isbn_extracted_even_next_to_another_number():
    text = "212945 9789897261367\n9789897261367"
    assert bf.extract_isbn(text) == "9789897261367"


def test_isbn_with_979_prefix_is_accepted():
    assert bf.extract_isbn("some text 9791234567896 more text") == "9791234567896"


def test_checksum_rejects_a_real_ocr_misread_with_right_shape():
    # 9789872613677 is a real observed OCR misread of the true ISBN
    # 9789897261367 (digit transposition) - same length/prefix, wrong checksum.
    assert bf.extract_isbn("9789897261367") == "9789897261367"
    assert bf.extract_isbn("9789872613677") is None


def test_isbn_not_starting_978_or_979_is_rejected():
    # 13 digits, but doesn't start with a valid ISBN-13 prefix
    assert bf.extract_isbn("1234567890123") is None


def test_empty_or_none_text_returns_none():
    assert bf.extract_isbn("") is None
    assert bf.extract_isbn(None) is None


# ------------------------- extract_title_author ------------------------ #

def test_extract_title_author_sends_expected_request(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse(200, {"response": '{"title": "Lago Perdido", "author": "Sarah Addison Allen"}'})

    monkeypatch.setattr(requests, "post", fake_post)

    result = bf.extract_title_author("LAGO PERDIDO\nSARAH ADISON ALLEN\nRomance Traduzido")

    assert result == {"title": "Lago Perdido", "author": "Sarah Addison Allen"}
    assert captured["url"].endswith("/api/generate")
    assert captured["json"]["format"] == "json"
    assert captured["json"]["model"]


def test_extract_title_author_returns_none_fields_not_empty_strings(monkeypatch):
    monkeypatch.setattr(
        requests, "post",
        lambda *a, **k: _FakeResponse(200, {"response": '{"title": null, "author": ""}'}),
    )

    result = bf.extract_title_author("illegible smudge")

    assert result == {"title": None, "author": None}


def test_extract_title_author_connection_failure_raises_filter_error(monkeypatch):
    def fake_post(*a, **k):
        raise requests.ConnectionError("nope")

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(bf.FilterError):
        bf.extract_title_author("some text")


def test_extract_title_author_bad_json_raises_filter_error(monkeypatch):
    monkeypatch.setattr(
        requests, "post",
        lambda *a, **k: _FakeResponse(200, {"response": "not valid json"}),
    )

    with pytest.raises(bf.FilterError):
        bf.extract_title_author("some text")


# --------------------------- filter_book_fields -------------------------- #

def test_filter_book_fields_combines_both(monkeypatch):
    monkeypatch.setattr(
        requests, "post",
        lambda *a, **k: _FakeResponse(200, {"response": '{"title": "T", "author": "A"}'}),
    )

    result = bf.filter_book_fields(
        cover_text="T by A",
        isbn_text="212945 9789897261367",
    )

    assert result == {"title": "T", "author": "A", "isbn": "9789897261367"}
