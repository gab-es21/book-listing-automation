import base64
from types import SimpleNamespace

import pytest
import requests
from PIL import Image

from blt import vision


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text or str(json_data)

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


@pytest.fixture
def sample_image(tmp_path):
    p = tmp_path / "cover.jpg"
    Image.new("RGB", (4, 4), color=(1, 2, 3)).save(p, "JPEG")
    return p


def test_read_cover_sends_expected_request_and_returns_text(monkeypatch, sample_image):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return _FakeResponse(200, {"response": "Uma Obsessao Indecente\nColleen McCullough"})

    monkeypatch.setattr(requests, "post", fake_post)

    text = vision.read_cover(sample_image)

    assert text == "Uma Obsessao Indecente\nColleen McCullough"
    assert captured["url"].endswith("/api/generate")
    assert captured["json"]["model"]  # some model name configured
    assert captured["json"]["stream"] is False
    assert len(captured["json"]["images"]) == 1
    # image was actually base64-encoded image bytes, not the raw path/string
    base64.b64decode(captured["json"]["images"][0])  # raises if not valid base64


def test_read_back_uses_a_different_isbn_focused_prompt(monkeypatch, sample_image):
    captured = {}

    def fake_post(url, json, timeout):
        captured["prompt"] = json["prompt"]
        return _FakeResponse(200, {"response": "9789896689704"})

    monkeypatch.setattr(requests, "post", fake_post)

    text = vision.read_back(sample_image)

    assert text == "9789896689704"
    assert "ISBN" in captured["prompt"]


def test_connection_failure_raises_vision_error_not_a_crash(monkeypatch, sample_image):
    def fake_post(*a, **k):
        raise requests.ConnectionError("nope")

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(vision.VisionError):
        vision.read_cover(sample_image)


def test_http_error_status_raises_vision_error(monkeypatch, sample_image):
    monkeypatch.setattr(requests, "post", lambda *a, **k: _FakeResponse(500, text="boom"))

    with pytest.raises(vision.VisionError):
        vision.read_cover(sample_image)


def test_malformed_response_raises_vision_error(monkeypatch, sample_image):
    monkeypatch.setattr(requests, "post", lambda *a, **k: _FakeResponse(200, json_data={"unexpected": "shape"}))

    with pytest.raises(vision.VisionError):
        vision.read_cover(sample_image)


def test_extract_book_text_reads_both_photos(monkeypatch, tmp_path):
    folder = tmp_path / "book_001"
    folder.mkdir()
    Image.new("RGB", (4, 4)).save(folder / "cover.jpg", "JPEG")
    Image.new("RGB", (4, 4)).save(folder / "back.jpg", "JPEG")

    seen_prompts = []

    def fake_post(url, json, timeout):
        seen_prompts.append(json["prompt"])
        return _FakeResponse(200, {"response": f"text-for-{len(seen_prompts)}"})

    monkeypatch.setattr(requests, "post", fake_post)

    result = vision.extract_book_text(folder)

    assert result == {"cover_text": "text-for-1", "back_text": "text-for-2"}
