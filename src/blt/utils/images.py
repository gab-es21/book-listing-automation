from pathlib import Path
from typing import List

def pick_last_n_images(folder: Path, n: int) -> List[Path]:
    imgs = [p for p in folder.glob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
    imgs.sort(key=lambda p: p.stat().st_mtime)  # cronológico
    return imgs[-n:] if len(imgs) >= n else []
