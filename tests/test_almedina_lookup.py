import pytest
import requests

from blt import almedina_lookup as al


class _FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


# Trimmed but structurally real HTML, matching what an actual product-page
# redirect from an exact ISBN match looks like (captured from a live lookup).
_PRODUCT_PAGE_HTML = """
<html><body>
<h1 itemprop="name">Sempre Tu</h1>
<span class="block-with-text-2">
  <a href='https://www.almedina.net/autor/colleen-hoover-1564061541'>Colleen Hoover</a>
</span>
</body></html>
"""

# A search-results listing (no exact ISBN match) doesn't carry the same
# structured product markup.
_NOT_FOUND_HTML = """
<html><body>
<div class="search-results">Sem resultados para a sua pesquisa.</div>
</body></html>
"""


def test_found_book_extracts_title_and_author(monkeypatch):
    monkeypatch.setattr(al.time, "sleep", lambda seconds: None)

    def fake_get(url, params, headers, timeout):
        assert params["q"] == "9789896689704"
        assert "User-Agent" in headers
        return _FakeResponse(200, _PRODUCT_PAGE_HTML)

    monkeypatch.setattr(requests, "get", fake_get)

    result = al.lookup_by_isbn("9789896689704")

    assert result == {"title": "Sempre Tu", "author": "Colleen Hoover"}


def test_not_found_returns_none(monkeypatch):
    monkeypatch.setattr(al.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(200, _NOT_FOUND_HTML))

    assert al.lookup_by_isbn("9780000000002") is None


def test_no_author_link_returns_none_author(monkeypatch):
    monkeypatch.setattr(al.time, "sleep", lambda seconds: None)
    html = '<html><body><h1 itemprop="name">Some Title</h1></body></html>'
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(200, html))

    result = al.lookup_by_isbn("9789896689704")

    assert result == {"title": "Some Title", "author": None}


def test_network_failure_raises_almedina_lookup_error(monkeypatch):
    monkeypatch.setattr(al.time, "sleep", lambda seconds: None)

    def fake_get(*a, **k):
        raise requests.ConnectionError("nope")

    monkeypatch.setattr(requests, "get", fake_get)

    with pytest.raises(al.AlmedinaLookupError):
        al.lookup_by_isbn("9789896689704")


def test_http_error_raises_almedina_lookup_error(monkeypatch):
    monkeypatch.setattr(al.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(403, "Forbidden"))

    with pytest.raises(al.AlmedinaLookupError):
        al.lookup_by_isbn("9789896689704")


def test_sleeps_a_small_random_delay_before_every_request(monkeypatch):
    sleeps = []
    monkeypatch.setattr(al.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(200, _PRODUCT_PAGE_HTML))

    al.lookup_by_isbn("9789896689704")

    assert len(sleeps) == 1
    assert 0.5 <= sleeps[0] <= 1.5
