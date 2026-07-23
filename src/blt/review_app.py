"""
Local-only FastAPI review page: one pending/failed book at a time, with
copy-paste-ready fields, plus a lightweight view for tracking sales of
already-listed books. Nothing here talks to Vinted - you paste the fields
yourself and click Next once the real listing exists.
"""
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import case, func, select

from . import db
from .models import Book

app = FastAPI(title="blt review")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

_UNREVIEWED = ("pending", "failed")
_PHOTO_NAMES = ("cover.jpg", "isbn.jpg")
_SORTABLE_COLUMNS = {
    "title": Book.title,
    "author": Book.author,
    "isbn": Book.isbn,
    "price": Book.price,
    "quantity": Book.quantity,
}
_PER_PAGE = 20
_VISIBLE_STATUSES = ("available", "sold_out")


@app.get("/", response_class=HTMLResponse)
def review_form(request: Request):
    with db.SessionLocal() as s:
        book = s.execute(
            select(Book).where(Book.status.in_(_UNREVIEWED)).order_by(Book.id)
        ).scalars().first()
        remaining = s.execute(
            select(func.count()).select_from(Book).where(Book.status.in_(_UNREVIEWED))
        ).scalar_one()
        return templates.TemplateResponse(
            request,
            "review.html",
            {"book": book, "remaining": remaining, "is_previous": False},
        )


@app.post("/next")
def submit_next(
    book_id: int = Form(...),
    title: str = Form(""),
    author: str = Form(""),
    isbn: str = Form(""),
    description: str = Form(""),
    price: float = Form(...),
    quantity: int = Form(1),
):
    with db.SessionLocal() as s:
        book = s.get(Book, book_id)
        if book is None:
            raise HTTPException(404)
        book.title = title or None
        book.author = author or None
        book.isbn = isbn or None
        book.description = description or None
        book.price = price
        book.quantity = quantity
        book.status = "available"
        s.commit()
    return RedirectResponse("/", status_code=303)


@app.get("/previous", response_class=HTMLResponse)
def previous_book(request: Request):
    with db.SessionLocal() as s:
        book = s.execute(
            select(Book)
            .where(Book.status == "available")
            .order_by(Book.updated_at.desc(), Book.id.desc())
        ).scalars().first()
        if book is None:
            raise HTTPException(404, "No previously-reviewed book yet.")
        return templates.TemplateResponse(
            request,
            "review.html",
            {"book": book, "remaining": None, "is_previous": True},
        )


@app.post("/revert/{book_id}")
def revert_to_pending(book_id: int):
    with db.SessionLocal() as s:
        book = s.get(Book, book_id)
        if book is None:
            raise HTTPException(404)
        book.status = "pending"
        s.commit()
    return RedirectResponse("/", status_code=303)


@app.get("/available", response_class=HTMLResponse)
def available_list(
    request: Request,
    q: str = "",
    sort: str = "title",
    dir: str = "asc",
    page: int = 1,
    view: str = "paginated",
):
    sort_col = _SORTABLE_COLUMNS.get(sort, Book.title)
    dir = "desc" if dir == "desc" else "asc"

    with db.SessionLocal() as s:
        base = select(Book).where(Book.status.in_(_VISIBLE_STATUSES))
        if q:
            like = f"%{q}%"
            base = base.where(
                Book.title.ilike(like) | Book.isbn.ilike(like) | Book.author.ilike(like)
            )

        total = s.execute(select(func.count()).select_from(base.subquery())).scalar_one()
        available_count = s.execute(
            select(func.count()).select_from(base.where(Book.status == "available").subquery())
        ).scalar_one()

        # sold_out rows always sort to the bottom, regardless of the chosen column
        sold_out_last = case((Book.status == "sold_out", 1), else_=0)
        ordered = base.order_by(sold_out_last, sort_col.desc() if dir == "desc" else sort_col.asc())

        if view == "all":
            books = s.execute(ordered).scalars().all()
            total_pages = 1
            page = 1
        else:
            view = "paginated"
            total_pages = max((total + _PER_PAGE - 1) // _PER_PAGE, 1)
            page = min(max(page, 1), total_pages)
            books = s.execute(ordered.limit(_PER_PAGE).offset((page - 1) * _PER_PAGE)).scalars().all()

        return templates.TemplateResponse(request, "available.html", {
            "books": books,
            "q": q,
            "sort": sort,
            "dir": dir,
            "page": page,
            "view": view,
            "total": total,
            "available_count": available_count,
            "sold_out_count": total - available_count,
            "total_pages": total_pages,
        })


@app.post("/sold/{book_id}")
def mark_one_sold(book_id: int):
    with db.SessionLocal() as s:
        book = s.get(Book, book_id)
        if book is None:
            raise HTTPException(404)
        book.quantity = max(book.quantity - 1, 0)
        if book.quantity == 0:
            book.status = "sold_out"
        s.commit()
    return RedirectResponse("/available", status_code=303)


@app.get("/photo/{book_id}/{name}")
def photo(book_id: int, name: str):
    if name not in _PHOTO_NAMES:
        raise HTTPException(404)
    with db.SessionLocal() as s:
        book = s.get(Book, book_id)
        if book is None:
            raise HTTPException(404)
        path = Path(book.folder_path) / name
        if not path.exists():
            raise HTTPException(404)
        return FileResponse(path)
