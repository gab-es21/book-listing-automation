import pytest
import requests

from blt import book_lookup


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return self._json


def test_found_book_returns_title_and_joined_authors(monkeypatch):
    def fake_get(url, params, timeout):
        assert params["q"] == "isbn:9789896689704"
        return _FakeResponse(200, {
            "items": [{"volumeInfo": {"title": "Lago Perdido", "authors": ["Sarah Addison Allen"]}}]
        })

    monkeypatch.setattr(requests, "get", fake_get)

    result = book_lookup.lookup_by_isbn("9789896689704")

    assert result == {"title": "Lago Perdido", "author": "Sarah Addison Allen"}


def test_multiple_authors_are_comma_joined(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(200, {
        "items": [{"volumeInfo": {"title": "T", "authors": ["A", "B"]}}]
    }))

    result = book_lookup.lookup_by_isbn("9789896689704")

    assert result == {"title": "T", "author": "A, B"}


def test_no_authors_field_returns_none_author(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(200, {
        "items": [{"volumeInfo": {"title": "T"}}]
    }))

    result = book_lookup.lookup_by_isbn("9789896689704")

    assert result == {"title": "T", "author": None}


def test_isbn_not_found_returns_none(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(200, {"items": []}))

    assert book_lookup.lookup_by_isbn("9780000000002") is None


def test_network_failure_raises_book_lookup_error(monkeypatch):
    def fake_get(*a, **k):
        raise requests.ConnectionError("nope")

    monkeypatch.setattr(requests, "get", fake_get)

    with pytest.raises(book_lookup.BookLookupError):
        book_lookup.lookup_by_isbn("9789896689704")


def test_quota_exceeded_raises_book_lookup_error(monkeypatch):
    # Real observed failure mode: Google Books free tier daily quota exhausted.
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(429, {"error": "quota exceeded"}))

    with pytest.raises(book_lookup.BookLookupError):
        book_lookup.lookup_by_isbn("9789896689704")
