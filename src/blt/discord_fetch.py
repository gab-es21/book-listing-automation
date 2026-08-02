"""
Pulls raw phone photos back out of a dedicated Discord channel into
RAW_DIR, as a faster alternative to a USB cable transfer. Plain Discord
REST API calls with a bot token - no discord.py, no persistent gateway
connection. This is a one-shot, on-demand fetch you run manually
(`blt fetch-discord-photos`), the same way `blt extract`/`group-all` are
run, not an always-on watcher.

DISCORD_BOT_TOKEN and DISCORD_PHOTOS_CHANNEL_ID are both required; unset
either and callers get a clear DiscordFetchError instead of a silent
no-op. That channel must be dedicated to this alone - never the same
channel DISCORD_WEBHOOK_URL (discord_notify.py) posts to, or this would
try to re-ingest the tool's own posted cover photos as new raw intake.
"""
import json
import os
from datetime import datetime
from pathlib import Path

import requests

from .config import settings
from .images import IMG_EXTS

_API_BASE = "https://discord.com/api/v10"
_PAGE_SIZE = 100
_STATE_PATH = Path(".discord_sync_state.json")


class DiscordFetchError(RuntimeError):
    pass


def _headers() -> dict:
    return {"Authorization": f"Bot {settings.DISCORD_BOT_TOKEN}"}


def _load_state() -> dict:
    if not _STATE_PATH.exists():
        return {"downloaded_attachment_ids": []}
    return json.loads(_STATE_PATH.read_text(encoding="utf-8"))


def _save_state(state: dict) -> None:
    _STATE_PATH.write_text(json.dumps(state), encoding="utf-8")


def _fetch_all_messages(channel_id: str) -> list[dict]:
    """
    Every message currently in the channel, oldest first. The channel is
    meant to stay small (successfully processed messages get deleted), so
    this walks it in full each run rather than tracking a resume cursor -
    simpler, and safe from ever permanently skipping a message that failed
    to fully process last time, since it's still sitting there to retry.
    """
    messages: list[dict] = []
    before = None
    while True:
        params: dict[str, int | str] = {"limit": _PAGE_SIZE}
        if before:
            params["before"] = before
        r = requests.get(f"{_API_BASE}/channels/{channel_id}/messages", headers=_headers(), params=params, timeout=20)
        r.raise_for_status()
        page = r.json()
        if not page:
            break
        messages.extend(page)
        before = str(min(int(m["id"]) for m in page))
        if len(page) < _PAGE_SIZE:
            break
    messages.sort(key=lambda m: int(m["id"]))
    return messages


def _delete_message(channel_id: str, message_id: str) -> bool:
    try:
        r = requests.delete(f"{_API_BASE}/channels/{channel_id}/messages/{message_id}", headers=_headers(), timeout=20)
        r.raise_for_status()
        return True
    except requests.RequestException:
        return False


def _is_image_attachment(attachment: dict) -> bool:
    content_type = attachment.get("content_type") or ""
    return content_type.startswith("image/") and Path(attachment["filename"]).suffix.lower() in IMG_EXTS


def fetch_new_photos(dest_dir: str | Path | None = None) -> dict:
    """
    Downloads every not-yet-seen image attachment from the configured
    Discord channel into dest_dir (RAW_DIR by default), sets each file's
    mtime to its message's own timestamp (so photo pairing sorts correctly
    even if Discord stripped EXIF), then deletes the message. A message
    whose download fails is left in the channel - already-downloaded
    attachments are recognized by ID and never re-downloaded, so the next
    run just retries the delete. Returns {"downloaded": N, "delete_failures": M}.
    """
    if not settings.DISCORD_BOT_TOKEN or not settings.DISCORD_PHOTOS_CHANNEL_ID:
        raise DiscordFetchError("DISCORD_BOT_TOKEN e/ou DISCORD_PHOTOS_CHANNEL_ID não estão configurados no .env.")

    dest = Path(dest_dir) if dest_dir is not None else Path(settings.RAW_DIR)
    dest.mkdir(parents=True, exist_ok=True)
    channel_id = settings.DISCORD_PHOTOS_CHANNEL_ID

    downloaded_ids: set[str] = set(_load_state()["downloaded_attachment_ids"])

    try:
        messages = _fetch_all_messages(channel_id)
    except requests.RequestException as e:
        raise DiscordFetchError(f"Não foi possível ler o canal do Discord ({e}).") from e

    downloaded_count = 0
    delete_failures = 0
    for message in messages:
        if message.get("author", {}).get("bot"):
            continue

        image_attachments = [a for a in message.get("attachments", []) if _is_image_attachment(a)]
        if not image_attachments:
            continue

        sent_at = datetime.fromisoformat(message["timestamp"]).timestamp()
        for attachment in image_attachments:
            if attachment["id"] in downloaded_ids:
                continue
            ext = Path(attachment["filename"]).suffix.lower()
            out_path = dest / f"discord_{message['id']}_{attachment['id']}{ext}"
            try:
                resp = requests.get(attachment["url"], timeout=30)
                resp.raise_for_status()
                out_path.write_bytes(resp.content)
                os.utime(out_path, (sent_at, sent_at))
            except requests.RequestException:
                continue
            downloaded_ids.add(attachment["id"])
            _save_state({"downloaded_attachment_ids": list(downloaded_ids)})
            downloaded_count += 1

        if all(a["id"] in downloaded_ids for a in image_attachments):
            if not _delete_message(channel_id, message["id"]):
                delete_failures += 1

    return {"downloaded": downloaded_count, "delete_failures": delete_failures}
