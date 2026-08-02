import json
from datetime import datetime

import pytest
import requests

from blt import discord_fetch as df


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, content=b""):
        self.status_code = status_code
        self._json_data = json_data
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return self._json_data


def _message(msg_id, timestamp="2024-01-15T10:30:00.000000+00:00", attachments=None, bot=False):
    return {
        "id": str(msg_id),
        "timestamp": timestamp,
        "author": {"id": "1", "bot": bot},
        "attachments": attachments or [],
    }


def _attachment(att_id, filename="photo.jpg", content_type="image/jpeg"):
    return {
        "id": str(att_id),
        "filename": filename,
        "content_type": content_type,
        "url": f"https://cdn.discordapp.com/attachments/x/{att_id}/{filename}",
    }


def _install_fakes(monkeypatch, pages, attachment_bytes=None, failing_urls=None, failing_message_ids=None):
    attachment_bytes = attachment_bytes or {}
    failing_urls = failing_urls or set()
    failing_message_ids = failing_message_ids or set()
    pages_iter = iter(pages)
    delete_calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.startswith(df._API_BASE):
            page = next(pages_iter, [])
            return _FakeResponse(200, json_data=page)
        if url in failing_urls:
            raise requests.ConnectionError("boom")
        return _FakeResponse(200, content=attachment_bytes.get(url, b"fake-bytes"))

    def fake_delete(url, headers=None, timeout=None):
        delete_calls.append(url)
        message_id = url.rsplit("/", 1)[-1]
        if message_id in failing_message_ids:
            raise requests.ConnectionError("boom")
        return _FakeResponse(200)

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "delete", fake_delete)
    return delete_calls


@pytest.fixture(autouse=True)
def _isolate_state_file(monkeypatch, tmp_path):
    monkeypatch.setattr(df, "_STATE_PATH", tmp_path / "state.json")


def _configure(monkeypatch):
    monkeypatch.setattr(df.settings, "DISCORD_BOT_TOKEN", "fake-token")
    monkeypatch.setattr(df.settings, "DISCORD_PHOTOS_CHANNEL_ID", "channel123")


def test_raises_when_bot_token_missing(monkeypatch):
    monkeypatch.setattr(df.settings, "DISCORD_BOT_TOKEN", "")
    monkeypatch.setattr(df.settings, "DISCORD_PHOTOS_CHANNEL_ID", "channel123")

    with pytest.raises(df.DiscordFetchError):
        df.fetch_new_photos()


def test_raises_when_channel_id_missing(monkeypatch):
    monkeypatch.setattr(df.settings, "DISCORD_BOT_TOKEN", "fake-token")
    monkeypatch.setattr(df.settings, "DISCORD_PHOTOS_CHANNEL_ID", "")

    with pytest.raises(df.DiscordFetchError):
        df.fetch_new_photos()


def test_downloads_image_attachment_sets_mtime_and_deletes_message(monkeypatch, tmp_path):
    _configure(monkeypatch)
    att = _attachment(1, filename="cover.jpg")
    msg = _message(100, timestamp="2024-01-15T10:30:00.000000+00:00", attachments=[att])
    delete_calls = _install_fakes(monkeypatch, pages=[[msg]], attachment_bytes={att["url"]: b"real-bytes"})

    dest = tmp_path / "raw"
    result = df.fetch_new_photos(dest_dir=dest)

    assert result == {"downloaded": 1, "delete_failures": 0}
    files = list(dest.glob("*.jpg"))
    assert len(files) == 1
    assert files[0].read_bytes() == b"real-bytes"

    expected_mtime = datetime.fromisoformat(msg["timestamp"]).timestamp()
    assert files[0].stat().st_mtime == pytest.approx(expected_mtime, abs=2)

    assert delete_calls == [f"{df._API_BASE}/channels/channel123/messages/100"]


def test_skips_non_image_attachments_and_leaves_message(monkeypatch, tmp_path):
    _configure(monkeypatch)
    att = _attachment(1, filename="notes.txt", content_type="text/plain")
    msg = _message(100, attachments=[att])
    delete_calls = _install_fakes(monkeypatch, pages=[[msg]])

    dest = tmp_path / "raw"
    result = df.fetch_new_photos(dest_dir=dest)

    assert result == {"downloaded": 0, "delete_failures": 0}
    assert not any(dest.iterdir()) if dest.exists() else True
    assert delete_calls == []


def test_skips_messages_from_bots(monkeypatch, tmp_path):
    _configure(monkeypatch)
    att = _attachment(1)
    msg = _message(100, attachments=[att], bot=True)
    delete_calls = _install_fakes(monkeypatch, pages=[[msg]])

    dest = tmp_path / "raw"
    result = df.fetch_new_photos(dest_dir=dest)

    assert result == {"downloaded": 0, "delete_failures": 0}
    assert delete_calls == []


def test_already_downloaded_attachment_is_not_redownloaded_but_delete_is_retried(monkeypatch, tmp_path):
    _configure(monkeypatch)
    att = _attachment(1)
    msg = _message(100, attachments=[att])
    get_call_urls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        get_call_urls.append(url)
        if url.startswith(df._API_BASE):
            return _FakeResponse(200, json_data=[msg] if len(get_call_urls) == 1 else [])
        return _FakeResponse(200, content=b"should-not-be-fetched-again")

    delete_calls = []

    def fake_delete(url, headers=None, timeout=None):
        delete_calls.append(url)
        return _FakeResponse(200)

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "delete", fake_delete)

    # Pre-seed state as if this attachment was already downloaded last run
    # (its message stuck around because the delete failed previously).
    df._save_state({"downloaded_attachment_ids": [att["id"]]})

    dest = tmp_path / "raw"
    result = df.fetch_new_photos(dest_dir=dest)

    assert result == {"downloaded": 0, "delete_failures": 0}
    assert att["url"] not in get_call_urls  # never re-fetched
    assert delete_calls == [f"{df._API_BASE}/channels/channel123/messages/100"]  # retried


def test_download_failure_leaves_message_undeleted(monkeypatch, tmp_path):
    _configure(monkeypatch)
    att = _attachment(1)
    msg = _message(100, attachments=[att])
    delete_calls = _install_fakes(monkeypatch, pages=[[msg]], failing_urls={att["url"]})

    dest = tmp_path / "raw"
    result = df.fetch_new_photos(dest_dir=dest)

    assert result == {"downloaded": 0, "delete_failures": 0}
    assert delete_calls == []  # never attempted - not all attachments succeeded
    state = df._load_state()
    assert att["id"] not in state["downloaded_attachment_ids"]


def test_message_only_deleted_once_all_its_attachments_succeed(monkeypatch, tmp_path):
    _configure(monkeypatch)
    ok_att = _attachment(1, filename="a.jpg")
    bad_att = _attachment(2, filename="b.jpg")
    msg = _message(100, attachments=[ok_att, bad_att])
    delete_calls = _install_fakes(monkeypatch, pages=[[msg]], failing_urls={bad_att["url"]})

    dest = tmp_path / "raw"
    result = df.fetch_new_photos(dest_dir=dest)

    assert result == {"downloaded": 1, "delete_failures": 0}
    assert delete_calls == []  # bad_att still missing, message kept for retry
    state = df._load_state()
    assert ok_att["id"] in state["downloaded_attachment_ids"]
    assert bad_att["id"] not in state["downloaded_attachment_ids"]


def test_delete_failure_is_reported_but_does_not_raise(monkeypatch, tmp_path):
    _configure(monkeypatch)
    att = _attachment(1)
    msg = _message(100, attachments=[att])
    _install_fakes(monkeypatch, pages=[[msg]], failing_message_ids={"100"})

    dest = tmp_path / "raw"
    result = df.fetch_new_photos(dest_dir=dest)

    assert result == {"downloaded": 1, "delete_failures": 1}


def test_listing_messages_http_error_raises_discord_fetch_error(monkeypatch, tmp_path):
    _configure(monkeypatch)

    def fake_get(url, headers=None, params=None, timeout=None):
        raise requests.ConnectionError("network down")

    monkeypatch.setattr(requests, "get", fake_get)

    with pytest.raises(df.DiscordFetchError):
        df.fetch_new_photos(dest_dir=tmp_path / "raw")


def test_pagination_combines_multiple_pages(monkeypatch, tmp_path):
    _configure(monkeypatch)
    monkeypatch.setattr(df, "_PAGE_SIZE", 1)

    att_a = _attachment(1, filename="a.jpg")
    att_b = _attachment(2, filename="b.jpg")
    msg_a = _message(100, attachments=[att_a])
    msg_b = _message(101, attachments=[att_b])
    # Two separate one-item pages, then an empty page to signal the end.
    _install_fakes(monkeypatch, pages=[[msg_b], [msg_a], []], attachment_bytes={
        att_a["url"]: b"a-bytes", att_b["url"]: b"b-bytes",
    })

    dest = tmp_path / "raw"
    result = df.fetch_new_photos(dest_dir=dest)

    assert result == {"downloaded": 2, "delete_failures": 0}
    assert {p.read_bytes() for p in dest.glob("*.jpg")} == {b"a-bytes", b"b-bytes"}


def test_state_file_persists_as_json(monkeypatch, tmp_path):
    _configure(monkeypatch)
    att = _attachment(1)
    msg = _message(100, attachments=[att])
    _install_fakes(monkeypatch, pages=[[msg]])

    df.fetch_new_photos(dest_dir=tmp_path / "raw")

    saved = json.loads(df._STATE_PATH.read_text(encoding="utf-8"))
    assert saved == {"downloaded_attachment_ids": [att["id"]]}
