import re
from datetime import datetime
from pathlib import Path

from PIL.ExifTags import IFD
from rich import print as rprint

from .config import settings
from .images import IMG_EXTS, load_image_any

_DATETIME_ORIGINAL = 36867  # Exif sub-IFD tag
_DATETIME = 306  # root IFD tag ("DateTime")


def _capture_time(p: Path) -> float:
    """Prefer EXIF DateTimeOriginal, then EXIF DateTime, then fall back to file mtime."""
    try:
        exif = load_image_any(p).getexif()
        dt_str = None
        try:
            dt_str = exif.get_ifd(IFD.Exif).get(_DATETIME_ORIGINAL)
        except Exception:
            pass
        dt_str = dt_str or exif.get(_DATETIME)
        if dt_str:
            return datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S").timestamp()
    except Exception:
        pass
    return p.stat().st_mtime


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


def _move_as_jpeg(src: Path, dest: Path):
    """Move src into dest, converting to JPEG unless it's already one (cheap rename then)."""
    if src.suffix.lower() in {".jpg", ".jpeg"}:
        src.replace(dest)
        return
    img = load_image_any(src).convert("RGB")
    img.save(dest, "JPEG", quality=95, optimize=True)
    src.unlink()


def group_last_set():
    """Creates a single group with the *latest* N images from RAW_DIR."""
    raw = Path(settings.RAW_DIR)
    grouped = Path(settings.GROUPED_DIR)
    imgs = [p for p in raw.glob("*") if p.suffix.lower() in IMG_EXTS]
    if not imgs:
        rprint("[yellow]Sem imagens em photos_raw/[/yellow]")
        return None

    imgs.sort(key=_capture_time)
    need = settings.PHOTOS_PER_BOOK
    if len(imgs) < need:
        rprint(f"[yellow]Não há fotos suficientes (precisa {need}).[/yellow]")
        return None

    last_n = imgs[-need:]
    dest = _make_dest(grouped, _next_book_index(grouped))
    _move_as_jpeg(last_n[0], dest / "cover.jpg")
    _move_as_jpeg(last_n[1], dest / "back.jpg")
    rprint(f"[green]Grupo criado:[/green] {dest}")
    return dest


def group_all(max_groups: int | None = None):
    """
    Agrupa TUDO o que houver em RAW_DIR em pares (capa, contracapa) por ordem
    cronológica (EXIF DateTimeOriginal, senão mtime do ficheiro).

    A primeira foto de cada par é sempre a capa, a segunda a contracapa. Uma
    foto sem par (contagem ímpar) fica em RAW_DIR com um aviso - nunca é
    emparelhada a adivinhar.

    max_groups: limite de quantos livros criar (None = todos os possíveis).
    """
    raw = Path(settings.RAW_DIR)
    grouped = Path(settings.GROUPED_DIR)

    imgs = [p for p in raw.glob("*") if p.suffix.lower() in IMG_EXTS]
    if not imgs:
        rprint("[yellow]Sem imagens em photos_raw/[/yellow]")
        return []

    imgs.sort(key=_capture_time)  # mais antiga primeiro
    need = 2  # capa + contracapa, sempre
    pairs_count = len(imgs) // need
    if pairs_count == 0:
        rprint(f"[yellow]Só há {len(imgs)} foto(s) - precisa de pelo menos {need}.[/yellow]")
        return []

    if max_groups is not None:
        pairs_count = min(pairs_count, max_groups)

    start_idx = _next_book_index(grouped)
    created = []

    for g in range(pairs_count):
        cover_src, back_src = imgs[g * need], imgs[g * need + 1]
        dest = _make_dest(grouped, start_idx + g)
        _move_as_jpeg(cover_src, dest / "cover.jpg")
        _move_as_jpeg(back_src, dest / "back.jpg")
        created.append(dest)
        rprint(f"[green]{dest.name}[/green]: capa={cover_src.name}, contracapa={back_src.name}")

    leftover = imgs[pairs_count * need:]
    if leftover:
        rprint(
            f"[yellow]Aviso: {len(leftover)} foto(s) sem par ficaram em {raw}/ "
            f"(não emparelhadas): {[p.name for p in leftover]}[/yellow]"
        )

    if created:
        rprint(f"[bold green]{len(created)} livro(s) agrupado(s).[/bold green]")
    return created
