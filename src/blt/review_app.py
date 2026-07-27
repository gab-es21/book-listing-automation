"""
Local-only FastAPI app covering the whole manual-assist flow as four steps,
always reachable from a persistent sidebar: raw images -> sorted images ->
detected book waiting confirmation -> stock. Nothing here talks to Vinted -
you paste the fields yourself and click Next once the real listing exists.
"""
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, case, func, or_, select

from . import db, group_photos
from .config import settings
from .extract import extract_pending_books
from .images import IMG_EXTS, load_image_any
from .models import Book, Sale

_HEIC_EXTS = {".heic", ".heif"}
_SAFE_ORIGIN_HOSTS = {"localhost", "127.0.0.1"}


def _serve_image(path: Path):
    """
    HEIC/HEIF is what phones actually produce, but no desktop browser can
    render it in an <img> tag - convert to JPEG on the fly for display only,
    the file on disk is never touched.
    """
    if path.suffix.lower() in _HEIC_EXTS:
        buf = BytesIO()
        load_image_any(path).convert("RGB").save(buf, "JPEG", quality=90)
        return Response(content=buf.getvalue(), media_type="image/jpeg")
    return FileResponse(path)

app = FastAPI(title="blt review")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.middleware("http")
async def reject_cross_origin_writes(request: Request, call_next):
    """
    This app has no auth by design (single-user localhost tool), so a
    state-changing request is only as trustworthy as knowing it actually
    came from this app's own pages. Modern browsers attach Origin to every
    POST, cross-origin or not, so a malicious site's hidden form targeting
    this port would show up here with a foreign Origin - reject it. A
    missing Origin/Referer (curl, scripts, the test suite) is let through:
    it means the request isn't a browser navigation in the first place.
    """
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        source = request.headers.get("origin") or request.headers.get("referer")
        if source and urlparse(source).hostname not in _SAFE_ORIGIN_HOSTS:
            return Response("Cross-origin request rejected.", status_code=403)
    return await call_next(request)

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

# A freshly-grouped book is status="pending" with title still NULL - the
# exact same shape extraction later fills in (still pending, title set) or
# fails out of (status="failed"). So the two states below partition cleanly
# without needing a new column: "sorted" is everything extraction hasn't
# touched yet, "review" is everything it has (resolved or not).
_SORTED_FILTER = and_(Book.status == "pending", Book.title.is_(None))
_REVIEW_FILTER = or_(Book.status == "failed", and_(Book.status == "pending", Book.title.is_not(None)))


def _sidebar_counts(s) -> dict:
    raw_dir = Path(settings.RAW_DIR)
    raw_count = len([p for p in raw_dir.glob("*") if p.suffix.lower() in IMG_EXTS]) if raw_dir.exists() else 0
    sorted_count = s.execute(select(func.count()).select_from(Book).where(_SORTED_FILTER)).scalar_one()
    review_count = s.execute(select(func.count()).select_from(Book).where(_REVIEW_FILTER)).scalar_one()
    stock_count = s.execute(
        select(func.count()).select_from(Book).where(Book.status == "available")
    ).scalar_one()
    return {
        "raw_count": raw_count,
        "sorted_count": sorted_count,
        "review_count": review_count,
        "stock_count": stock_count,
    }


def _metrics(s) -> dict:
    weekly_sales = s.execute(
        select(
            func.strftime("%Y-W%W", Sale.sold_at).label("week"),
            func.count(Sale.id).label("count"),
            func.sum(Sale.price).label("revenue"),
        ).group_by("week").order_by(func.strftime("%Y-W%W", Sale.sold_at).desc())
    ).all()
    weekly_added = s.execute(
        select(
            func.strftime("%Y-W%W", Book.created_at).label("week"),
            func.count(Book.id).label("count"),
        ).group_by("week").order_by(func.strftime("%Y-W%W", Book.created_at).desc())
    ).all()
    total_revenue = s.execute(select(func.sum(Sale.price))).scalar_one() or 0.0
    total_sold = s.execute(select(func.count(Sale.id))).scalar_one()
    return {
        "weekly_sales": weekly_sales,
        "weekly_added": weekly_added,
        "total_revenue": total_revenue,
        "total_sold": total_sold,
        "revenue_chart": _bar_chart_data([(row.week, row.revenue) for row in weekly_sales]),
        "added_chart": _bar_chart_data([(row.week, row.count) for row in weekly_added]),
    }


def _bar_chart_data(pairs: list) -> list:
    """
    pairs: [(label, value), ...] most-recent-first (as the weekly queries
    return them for the table). Returns the same data oldest-first (so the
    chart reads left-to-right forward in time) with each value's height as a
    0-100 percentage of the series max, ready for an SVG bar to consume
    directly without doing math in the template.
    """
    items = list(reversed(pairs))
    max_v = max((v or 0) for _, v in items) if items else 0
    return [
        {"label": label, "value": v or 0, "pct": round((v or 0) / max_v * 100, 1) if max_v else 0}
        for label, v in items
    ]


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    with db.SessionLocal() as s:
        ctx = _sidebar_counts(s)
        metrics = _metrics(s)
        return templates.TemplateResponse(request, "dashboard.html", {**ctx, **metrics, "active_step": None})


# -------- Raw images --------

@app.get("/raw", response_class=HTMLResponse)
def raw_images(request: Request):
    pairs, leftover = group_photos.propose_pairs()
    with db.SessionLocal() as s:
        ctx = _sidebar_counts(s)
        return templates.TemplateResponse(
            request, "raw.html", {**ctx, "active_step": "raw", "pairs": pairs, "leftover": leftover}
        )


@app.get("/raw-photo/{filename}")
def raw_photo(filename: str):
    path = Path(settings.RAW_DIR) / Path(filename).name
    if not path.exists() or path.suffix.lower() not in IMG_EXTS:
        raise HTTPException(404)
    return _serve_image(path)


@app.post("/raw/confirm-all")
def confirm_all_pairs():
    group_photos.group_all()
    db.sync_pending_books(settings.GROUPED_DIR)
    return RedirectResponse("/raw", status_code=303)


@app.post("/raw/confirm-pair")
def confirm_one_pair(photo_a: str = Form(...), photo_b: str = Form(...), swap: str = Form("")):
    raw_dir = Path(settings.RAW_DIR)
    a, b = raw_dir / Path(photo_a).name, raw_dir / Path(photo_b).name
    cover, isbn = (b, a) if swap else (a, b)
    if not cover.exists() or not isbn.exists():
        raise HTTPException(404, "Uma das fotos já não está em photos_raw/.")
    group_photos.commit_pair(cover, isbn)
    db.sync_pending_books(settings.GROUPED_DIR)
    return RedirectResponse("/raw", status_code=303)


# -------- Sorted images --------

@app.get("/sorted", response_class=HTMLResponse)
def sorted_images(request: Request):
    with db.SessionLocal() as s:
        books = s.execute(select(Book).where(_SORTED_FILTER).order_by(Book.id)).scalars().all()
        ctx = _sidebar_counts(s)
        return templates.TemplateResponse(
            request, "sorted.html", {**ctx, "active_step": "sorted", "books": books}
        )


@app.post("/sorted/detect")
def detect_books():
    extract_pending_books()
    return RedirectResponse("/sorted", status_code=303)


# -------- Detected book waiting confirmation --------

@app.get("/review", response_class=HTMLResponse)
def review_form(request: Request, after: int = 0):
    with db.SessionLocal() as s:
        query = select(Book).where(_REVIEW_FILTER).order_by(Book.id)
        book = None
        if settings.DEV_MODE and after:
            # cyclic cursor: next unresolved/failed book after the last one
            # shown, wrapping back to the first - DEV_MODE never promotes
            # anything to available, so nothing is ever consumed.
            book = s.execute(query.where(Book.id > after)).scalars().first()
        if book is None:
            book = s.execute(query).scalars().first()
        ctx = _sidebar_counts(s)
        return templates.TemplateResponse(
            request,
            "review.html",
            {**ctx, "active_step": "review", "book": book, "remaining": ctx["review_count"],
             "is_previous": False, "dev_mode": settings.DEV_MODE},
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
        if not settings.DEV_MODE:
            book.status = "available"
        s.commit()
    if settings.DEV_MODE:
        return RedirectResponse(f"/review?after={book_id}", status_code=303)
    return RedirectResponse("/review", status_code=303)


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
        ctx = _sidebar_counts(s)
        return templates.TemplateResponse(
            request,
            "review.html",
            {**ctx, "active_step": "review", "book": book, "remaining": None,
             "is_previous": True, "dev_mode": settings.DEV_MODE},
        )


@app.post("/revert/{book_id}")
def revert_to_pending(book_id: int):
    with db.SessionLocal() as s:
        book = s.get(Book, book_id)
        if book is None:
            raise HTTPException(404)
        book.status = "pending"
        s.commit()
    return RedirectResponse("/review", status_code=303)


# -------- Stock --------

@app.get("/stock", response_class=HTMLResponse)
def stock_list(
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

        ctx = _sidebar_counts(s)
        return templates.TemplateResponse(request, "available.html", {
            **ctx,
            "active_step": "stock",
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
        s.add(Sale(book_id=book.id, title=book.title, isbn=book.isbn, price=book.price))
        book.quantity = max(book.quantity - 1, 0)
        if book.quantity == 0:
            book.status = "sold_out"
        s.commit()
    return RedirectResponse("/stock", status_code=303)


@app.post("/stock/edit/{book_id}")
def update_book_in_stock(
    book_id: int,
    title: str = Form(""),
    author: str = Form(""),
    isbn: str = Form(""),
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
        book.price = price
        book.quantity = quantity
        book.status = "sold_out" if quantity <= 0 else "available"
        s.commit()
    return RedirectResponse("/stock", status_code=303)


@app.post("/delete/{book_id}")
def delete_book(book_id: int):
    with db.SessionLocal() as s:
        book = s.get(Book, book_id)
        if book is None:
            raise HTTPException(404)
        s.delete(book)
        s.commit()
    return RedirectResponse("/stock", status_code=303)


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
