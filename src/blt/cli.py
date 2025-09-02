import typer
from pathlib import Path
from rich import print
from .db import SessionLocal, init_db
from .models import Book, Listing, BookPhoto
from .group_photos import group_last_set
from .describe_book import describe_book_from_folder
from .post_vinted import post_vinted
from .storage import upload_photos_and_get_urls

app = typer.Typer(help="Book Listing Automation")

@app.command()
def initdb():
    init_db()
    print("[green]DB pronta.[/green]")

@app.command()
def group():
    group_last_set()

@app.command()
def describe(folder: str):
    meta = describe_book_from_folder(Path(folder))
    print(meta)

@app.command()
def vinted(folder: str, headless: bool = False, upload_storage: bool = False):
    init_db()
    folder_path = Path(folder)
    meta = describe_book_from_folder(folder_path)  # usa upload temp + cleanup
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
        s.add(book); s.flush()

        # opcional: guardar fotos permanentemente (normalmente False p/ não gastar quota)
        if upload_storage:
            slug = folder_path.name
            try:
                urls = upload_photos_and_get_urls(folder_path, slug)
                for idx, u in enumerate(urls, start=1):
                    s.add(BookPhoto(book_id=book.id, url=u, idx=idx))
            except Exception as e:
                print(f"[yellow]Aviso: upload Storage falhou: {e}[/yellow]")

        s.add(Listing(book_id=book.id, platform="vinted", listing_url=url, status="posted"))
        s.commit()
    print(f"[green]Publicado:[/green] {url}")

@app.command()
def full(headless: bool = False, upload_storage: bool = False):
    init_db()
    dest = group_last_set()
    if not dest:
        return
    meta = describe_book_from_folder(dest)  # upload temp + cleanup
    url = post_vinted(dest, meta, headless=headless)
    if not url:
        print("[red]Falha a publicar no Vinted.[/red]")
        return

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

        if upload_storage:
            slug = dest.name
            try:
                urls = upload_photos_and_get_urls(dest, slug)
                for idx, u in enumerate(urls, start=1):
                    s.add(BookPhoto(book_id=book.id, url=u, idx=idx))
            except Exception as e:
                print(f"[yellow]Aviso: upload Storage falhou: {e}[/yellow]")

        s.add(Listing(book_id=book.id, platform="vinted", listing_url=url, status="posted"))
        s.commit()
    print(f"[green]OK:[/green] {url}")

if __name__ == "__main__":
    app()
