"""
Loads the configurable list of marketplaces a book can be cross-posted to,
from platforms.json at the project root. Lets that set grow (layout assumes
around 5) without any code change - just edit the file. Re-read on every
call rather than cached, so editing the file takes effect on the next page
load without restarting `blt review`.
"""
import json
from pathlib import Path
from typing import NamedTuple

_CONFIG_PATH = Path("platforms.json")


class Platform(NamedTuple):
    slug: str
    name: str
    domain: str
    default: bool = False
    icon: str | None = None

    @property
    def icon_url(self) -> str:
        # icon lets a platform override the auto-derived favicon (e.g. if a
        # domain's favicon looks wrong) - otherwise fetched live from the
        # browser at render time, nothing downloaded/cached server-side.
        return self.icon or f"https://www.google.com/s2/favicons?domain={self.domain}&sz=16"


def load_platforms() -> list[Platform]:
    if not _CONFIG_PATH.exists():
        return []
    data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    return [Platform(**entry) for entry in data]
