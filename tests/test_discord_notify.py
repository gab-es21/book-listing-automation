import json

import pytest
import requests

from blt import discord_notify as dn


class _FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


def test_raises_when_webhook_not_configured(monkeypatch):
    monkeypatch.setattr(dn.settings, "DISCORD_WEBHOOK_URL", "")

    with pytest.raises(dn.DiscordNotifyError):
        dn.post_message("hello")


def test_posts_plain_json_when_no_files(monkeypatch):
    monkeypatch.setattr(dn.settings, "DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/x/y")
    calls = []

    def fake_post(url, json=None, timeout=None, **kwargs):
        calls.append((url, json))
        return _FakeResponse(200)

    monkeypatch.setattr(requests, "post", fake_post)

    dn.post_message("hello world")

    assert len(calls) == 1
    url, payload = calls[0]
    assert url == "https://discord.com/api/webhooks/x/y"
    assert payload == {"content": "hello world"}


def test_posts_multipart_with_files_attached(monkeypatch):
    monkeypatch.setattr(dn.settings, "DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/x/y")
    calls = []

    def fake_post(url, data=None, files=None, timeout=None, **kwargs):
        calls.append((url, data, files))
        return _FakeResponse(200)

    monkeypatch.setattr(requests, "post", fake_post)

    dn.post_message("with a photo", files=[("cover.jpg", b"fake-bytes", "image/jpeg")])

    assert len(calls) == 1
    url, data, files = calls[0]
    assert url == "https://discord.com/api/webhooks/x/y"
    assert json.loads(data["payload_json"]) == {"content": "with a photo"}
    assert files == {"files[0]": ("cover.jpg", b"fake-bytes", "image/jpeg")}


def test_network_failure_raises_discord_notify_error(monkeypatch):
    monkeypatch.setattr(dn.settings, "DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/x/y")

    def fake_post(*a, **k):
        raise requests.ConnectionError("nope")

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(dn.DiscordNotifyError):
        dn.post_message("hello")


def test_http_error_raises_discord_notify_error(monkeypatch):
    monkeypatch.setattr(dn.settings, "DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/x/y")
    monkeypatch.setattr(requests, "post", lambda *a, **k: _FakeResponse(403))

    with pytest.raises(dn.DiscordNotifyError):
        dn.post_message("hello")
