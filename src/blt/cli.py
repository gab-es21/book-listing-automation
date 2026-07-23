import typer
from pathlib import Path
from rich import print
from .db import init_db
from .group_photos import group_last_set

app = typer.Typer(help="Book Listing Automation")

@app.command()
def initdb():
    init_db()
    print("[green]DB pronta.[/green]")

@app.command()
def group():
    group_last_set()

@app.command("group-all")
def group_all_cmd(max_groups: int = typer.Option(None, help="Limite de grupos a criar (por omissão, todos)")):
    """Agrupa TUDO o que houver em photos_raw/ em blocos de PHOTOS_PER_BOOK."""
    from .group_photos import group_all as _group_all
    _group_all(max_groups=max_groups)

@app.command("convert-heic")
def convert_heic(path: str, recursive: bool = True, delete_src: bool = True):
    """Convert all .heic/.heif under PATH to .jpg (deletes originals by default)."""
    from .heic_convert import convert_folder
    created = convert_folder(Path(path), recursive=recursive, delete_src=delete_src)
    print(f"[green]{len(created)} ficheiro(s) convertidos para JPEG.[/green]")

if __name__ == "__main__":
    app()
