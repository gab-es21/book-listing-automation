import pytest
import requests

from blt import isbnsearch_lookup as isl


class _FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


# Trimmed but structurally real HTML, captured from a live isbnsearch.org
# product page.
_PRODUCT_PAGE_HTML = """
<html><body>
<div class="bookinfo">
  <h1>A villa</h1>
  <p><strong>ISBN-13:</strong> <a href="/isbn/9789898032577">9789898032577</a></p>
  <p><strong>ISBN-10:</strong> <a href="/isbn/989803257X">989803257X</a></p>
  <p><strong>Author:</strong> Nora Roberts</p>
  <p><strong>Binding:</strong> Paperback</p>
  <p><strong>Publisher:</strong> Chã das Cinco</p>
  <p><strong>Published:</strong> 2009</p>
</div>
</body></html>
"""

_NO_AUTHOR_HTML = """
<html><body>
<div class="bookinfo">
  <h1>Some Title</h1>
  <p><strong>ISBN-13:</strong> <a href="/isbn/9789898032577">9789898032577</a></p>
</div>
</body></html>
"""


def test_found_book_extracts_title_and_author(monkeypatch):
    monkeypatch.setattr(isl.time, "sleep", lambda seconds: None)

    def fake_get(url, headers, timeout):
        assert url == isl.BASE_URL + "9789898032577"
        assert "User-Agent" in headers
        return _FakeResponse(200, _PRODUCT_PAGE_HTML)

    monkeypatch.setattr(requests, "get", fake_get)

    result = isl.lookup_by_isbn("9789898032577")

    assert result == {"title": "A villa", "author": "Nora Roberts"}


def test_not_found_returns_none_on_404(monkeypatch):
    monkeypatch.setattr(isl.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(404, "Not Found"))

    assert isl.lookup_by_isbn("0000000000000") is None


def test_no_bookinfo_returns_none(monkeypatch):
    monkeypatch.setattr(isl.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(200, "<html><body>nope</body></html>"))

    assert isl.lookup_by_isbn("9789898032577") is None


def test_bookinfo_without_title_returns_none(monkeypatch):
    monkeypatch.setattr(isl.time, "sleep", lambda seconds: None)
    html = '<html><body><div class="bookinfo"><p>no title here</p></div></body></html>'
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(200, html))

    assert isl.lookup_by_isbn("9789898032577") is None


def test_no_author_field_returns_none_author(monkeypatch):
    monkeypatch.setattr(isl.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(200, _NO_AUTHOR_HTML))

    result = isl.lookup_by_isbn("9789898032577")

    assert result == {"title": "Some Title", "author": None}


def test_network_failure_raises_isbnsearch_lookup_error(monkeypatch):
    monkeypatch.setattr(isl.time, "sleep", lambda seconds: None)

    def fake_get(*a, **k):
        raise requests.ConnectionError("nope")

    monkeypatch.setattr(requests, "get", fake_get)

    with pytest.raises(isl.IsbnSearchLookupError):
        isl.lookup_by_isbn("9789898032577")


def test_http_error_raises_isbnsearch_lookup_error(monkeypatch):
    monkeypatch.setattr(isl.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(500, "Server Error"))

    with pytest.raises(isl.IsbnSearchLookupError):
        isl.lookup_by_isbn("9789898032577")


def test_sleeps_a_small_random_delay_before_every_request(monkeypatch):
    sleeps = []
    monkeypatch.setattr(isl.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(200, _PRODUCT_PAGE_HTML))

    isl.lookup_by_isbn("9789898032577")

    assert len(sleeps) == 1
    assert 0.5 <= sleeps[0] <= 1.5
