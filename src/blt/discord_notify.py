"""
Discord webhook notifications for the review-page sorting list and the
stock list - a one-way push so both are checkable from a phone without
opening the local web app. A webhook is a single URL (no bot process, no
token beyond the URL itself, nothing that needs to run continuously) - the
simplest fit for a one-way "post a message" need.

DISCORD_WEBHOOK_URL is optional; when it's unset, callers get a clear
DiscordNotifyError instead of a silent no-op.
"""
import json

import requests

from .config import settings


class DiscordNotifyError(RuntimeError):
    pass


def post_message(content: str, files: list[tuple[str, bytes, str]] | None = None) -> None:
    """
    Posts one message to the configured Discord webhook. `files` is a list
    of (filename, raw_bytes, mime_type) tuples attached alongside the text -
    Discord webhooks accept up to 10 attachments per message; splitting a
    larger set into several messages is the caller's responsibility, as is
    keeping `content` under Discord's 2000-character message limit.
    """
    if not settings.DISCORD_WEBHOOK_URL:
        raise DiscordNotifyError("DISCORD_WEBHOOK_URL não está configurado no .env.")

    try:
        if files:
            request_files = {f"files[{i}]": (name, data, mime) for i, (name, data, mime) in enumerate(files)}
            r = requests.post(
                settings.DISCORD_WEBHOOK_URL,
                data={"payload_json": json.dumps({"content": content})},
                files=request_files,
                timeout=20,
            )
        else:
            r = requests.post(settings.DISCORD_WEBHOOK_URL, json={"content": content}, timeout=20)
        r.raise_for_status()
    except requests.RequestException as e:
        raise DiscordNotifyError(f"Não foi possível enviar para o Discord ({e}).") from e
