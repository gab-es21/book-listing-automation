from pathlib import Path
from rich import print
from .config import settings
import re

def next_book_folder(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    existing = [p for p in base.iterdir() if p.is_dir() and re.match(r"book_\d{3,}", p.name)]
    idx = 1
    if existing:
        nums = [int(p.name.split("_")[1]) for p in existing]
        idx = max(nums) + 1
    dest = base / f"book_{idx:03d}"
    dest.mkdir()
    return dest

def group_last_set():
    raw = Path(settings.RAW_DIR)
    grouped = Path(settings.GROUPED_DIR)
    imgs = [p for p in raw.glob("*") if p.suffix.lower() in {".jpg",".jpeg",".png",".webp"}]
    imgs.sort(key=lambda p: p.stat().st_mtime)
    need = settings.PHOTOS_PER_BOOK
    if len(imgs) < need:
        print(f"[yellow]Não há fotos suficientes (precisa {need}).[/yellow]")
        return None
    last_n = imgs[-need:]
    dest = next_book_folder(grouped)
    for i, src in enumerate(last_n, start=1):
        src.rename(dest / f"{i:02d}{src.suffix.lower()}")
    print(f"[green]Grupo criado:[/green] {dest}")
    return dest

if __name__ == "__main__":
    group_last_set()
