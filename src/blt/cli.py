import typer
from pathlib import Path
from rich import print
from .config import settings
from .db import SessionLocal, init_db
from .models import Book, Listing
from .group_photos import group_last_set
from .describe_book import describe_book_from_folder
from .post_vinted import post_vinted

app = typer.Typer(help="Book Listing Automation")

@app.command()
def initdb():
    init_db()
    print("[green]DB pronta.[/green]")

@app.command()
def group():
    """Agrupa as últimas N fotos (N=.env PHOTOS_PER_BOOK) numa pasta book_XXX em photos_grouped/."""
    group_last_set()

@app.command()
def describe(folder: str):
    meta = describe_book_from_folder(Path(folder))
    print(meta)

@app.command()
def vinted(folder: str, headless: bool = False):
    """Publica no Vinted e guarda no DB."""
    init_db()
    folder_path = Path(folder)
    meta = describe_book_from_folder(folder_path)
    url = post_vinted(folder_path, meta, headless=headless)
    if not url:
        print("[red]Falha a obter URL do anúncio.[/red]")
        raise typer.Exit(code=1)

    with SessionLocal() as s:
        book = Book(
            title=meta["title"],
            description=meta["description"],
            price=meta["price"],
            quantity=1,
            status="available",
            folder_path=str(folder_path),
        )
        s.add(book)
        s.flush()
        s.add(Listing(book_id=book.id, platform="vinted", listing_url=url, status="posted"))
        s.commit()
    print(f"[green]Publicado:[/green] {url}")

@app.command()
def full(headless: bool = False):
    """Agrupa -> Descreve -> Publica no Vinted -> Persiste no DB."""
    init_db()
    dest = group_last_set()
    if not dest:
        return
    meta = describe_book_from_folder(dest)
    url = post_vinted(dest, meta, headless=headless)
    if not url:
        print("[red]Falha a publicar no Vinted.[/red]")
        return
    from .db import SessionLocal
    from .models import Book, Listing
    with SessionLocal() as s:
        book = Book(
            title=meta["title"],
            description=meta["description"],
            price=meta["price"],
            quantity=1,
            status="available",
            folder_path=str(dest),
        )
        s.add(book); s.flush()
        s.add(Listing(book_id=book.id, platform="vinted", listing_url=url, status="posted"))
        s.commit()
    print(f"[green]OK:[/green] {url}")

if __name__ == "__main__":
    app()
