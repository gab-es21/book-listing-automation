from pathlib import Path
from rich import print
from .config import settings
import re

IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}

def _next_book_index(base: Path) -> int:
    base.mkdir(parents=True, exist_ok=True)
    existing = [p for p in base.iterdir() if p.is_dir() and re.match(r"book_\d{3,}$", p.name)]
    if not existing:
        return 1
    nums = [int(p.name.split("_")[1]) for p in existing]
    return max(nums) + 1

def _make_dest(base: Path, index: int) -> Path:
    dest = base / f"book_{index:03d}"
    dest.mkdir(parents=True, exist_ok=True)
    return dest

def group_last_set():
    """
    Creates a single group with the *latest* N images from RAW_DIR.
    """
    raw = Path(settings.RAW_DIR)
    grouped = Path(settings.GROUPED_DIR)
    imgs = [p for p in raw.glob("*") if p.suffix.lower() in IMG_EXTS]
    if not imgs:
        print("[yellow]Sem imagens em photos_raw/[/yellow]")
        return None

    imgs.sort(key=lambda p: p.stat().st_mtime)  # chronological
    need = settings.PHOTOS_PER_BOOK
    if len(imgs) < need:
        print(f"[yellow]Não há fotos suficientes (precisa {need}).[/yellow]")
        return None

    last_n = imgs[-need:]
    start_idx = _next_book_index(grouped)
    dest = _make_dest(grouped, start_idx)
    for i, src in enumerate(last_n, start=1):
        src.rename(dest / f"{i:02d}{src.suffix.lower()}")
    print(f"[green]Grupo criado:[/green] {dest}")
    return dest

def group_all(max_groups: int | None = None):
    """
    Batch groups ALL available photos in RAW_DIR into book_xxx folders,
    using PHOTOS_PER_BOOK per group, oldest → newest.

    max_groups: limit how many groups to create (None = all possible).
    """
    raw = Path(settings.RAW_DIR)
    grouped = Path(settings.GROUPED_DIR)

    imgs = [p for p in raw.glob("*") if p.suffix.lower() in IMG_EXTS]
    if not imgs:
        print("[yellow]Sem imagens em photos_raw/[/yellow]")
        return []

    imgs.sort(key=lambda p: p.stat().st_mtime)  # oldest first
    need = settings.PHOTOS_PER_BOOK
    full_groups = len(imgs) // need
    if full_groups == 0:
        print(f"[yellow]Não há fotos suficientes para um grupo de {need}.[/yellow]")
        return []

    if max_groups is not None:
        full_groups = min(full_groups, max_groups)

    start_idx = _next_book_index(grouped)
    created = []

    for g in range(full_groups):
        batch = imgs[g*need:(g+1)*need]
        dest = _make_dest(grouped, start_idx + g)
        for i, src in enumerate(batch, start=1):
            src.rename(dest / f"{i:02d}{src.suffix.lower()}")
        created.append(dest)
        print(f"[green]Grupo {dest.name} criado com {need} fotos.[/green]")

    leftover = len(imgs) - full_groups * need
    if leftover:
        print(f"[cyan]{leftover} foto(s) ficaram em photos_raw/ (incompletas para novo grupo).[/cyan]")

    if created:
        print(f"[bold green]{len(created)} grupo(s) criados.[/bold green]")
    return created
