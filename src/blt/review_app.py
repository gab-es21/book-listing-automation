"""
Local-only FastAPI app covering the whole manual-assist flow as four steps,
always reachable from a persistent sidebar: raw images -> sorted images ->
detected book waiting confirmation -> stock. Nothing here talks to Vinted -
you paste the fields yourself and click Next once the real listing exists.
"""
import random
import shutil
import threading
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, case, func, or_, select

from . import db, discord_notify, group_photos
from .config import settings
from .extract import _extract_with_dev_cache, extract_book_fields, extract_pending_books
from .images import IMG_EXTS, load_image_any
from .listing import compose_listing
from .models import Book, Sale

_HEIC_EXTS = {".heic", ".heif"}
_SAFE_ORIGIN_HOSTS = {"localhost", "127.0.0.1"}

# "Procurar todos novamente" runs in a background thread (the paced,
# multi-book run can take a while) - this is the only state it reports back
# to the page polling /reextract-all/status. Single-process, single-user
# app, so a plain dict + lock is enough; no real concurrency to worry about.
_bulk_reextract_lock = threading.Lock()
_bulk_reextract_state: dict = {"running": False, "current": 0, "total": 0, "book_label": None}


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
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


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
_STOCKED_STATUSES = ("available", "sold_out")


def _find_isbn_duplicate(s, book: Book) -> Book | None:
    """Another already-stocked book (available/sold_out) sharing this ISBN, if any."""
    if not book.isbn:
        return None
    return s.execute(
        select(Book).where(Book.isbn == book.isbn, Book.id != book.id, Book.status.in_(_STOCKED_STATUSES))
    ).scalars().first()


def _classify_review_book(s, book: Book) -> str:
    """One of "red" (no ISBN at all), "grey" (ISBN but nothing resolved),
    "yellow" (resolved, but ISBN already stocked - a duplicate), or "green"
    (resolved, unique, just needs confirming)."""
    if not book.isbn:
        return "red"
    if not book.title:
        return "grey"
    if _find_isbn_duplicate(s, book) is not None:
        return "yellow"
    return "green"


def _review_queue_breakdown(s) -> dict:
    books = s.execute(select(Book).where(_REVIEW_FILTER)).scalars().all()
    counts = {"red": 0, "grey": 0, "yellow": 0, "green": 0}
    for book in books:
        counts[_classify_review_book(s, book)] += 1
    total = len(books)

    def _pct(x):
        return round(x / total * 100, 1) if total else 0.0

    return {
        "review_red_count": counts["red"], "review_grey_count": counts["grey"],
        "review_yellow_count": counts["yellow"], "review_green_count": counts["green"],
        "review_red_pct": _pct(counts["red"]), "review_grey_pct": _pct(counts["grey"]),
        "review_yellow_pct": _pct(counts["yellow"]), "review_green_pct": _pct(counts["green"]),
        # width of one book, as a % of the whole bar - same trick as the main
        # progress bar's unit_pct, for a tick mark per book.
        "review_unit_pct": round(100 / total, 4) if total else 0,
    }


_DISCORD_MAX_ATTACHMENTS = 10
_DISCORD_MAX_CONTENT = 1900  # a little under Discord's 2000-char cap, room for the header line

_PHYSICAL_PILE_TITLES = {
    "foto": "📸 Tirar nova foto (ISBN não detetado)",
    "manual": "✋ Inserir à mão (ISBN não encontrado)",
    "vender": "✅ Pronto para vender",
}
_PHYSICAL_PILE_ORDER = ["foto", "manual", "vender"]


def _physical_pile(s, book: Book) -> tuple[str, str]:
    """Maps a review book to one of the 3 piles the user actually acts on
    physically - unlike the 4-way red/grey/yellow/green classification
    above, which also distinguishes a bookkeeping detail (duplicate merge)
    that doesn't change where the physical book goes. Returns
    (pile_key, a note to append for that book, e.g. "already in stock")."""
    classification = _classify_review_book(s, book)
    if classification == "red":
        return "foto", ""
    if classification == "grey":
        return "manual", ""
    if classification == "yellow":
        return "vender", " _(já em stock, vai somar quantidade)_"
    return "vender", ""


def _review_book_line(book: Book, note: str = "") -> str:
    parts = [f"`{Path(book.folder_path).name}`"]
    if book.title:
        parts.append(f"**{book.title}**" + (f" — {book.author}" if book.author else ""))
    if book.isbn:
        parts.append(f"ISBN {book.isbn}")
    return "- " + " · ".join(parts) + note


def send_review_sort_list_to_discord(s) -> int:
    """Groups every book still in the review queue into the 3 physical
    sorting piles and posts one Discord message per pile (split further if
    a pile has more books than Discord's 10-attachment-per-message limit),
    each with its cover photo attached alongside the book_NNN id so it's
    easy to match the message to the physical book. Returns how many books
    were sent."""
    books = s.execute(select(Book).where(_REVIEW_FILTER).order_by(Book.id)).scalars().all()
    piles: dict[str, list[tuple[Book, str]]] = {key: [] for key in _PHYSICAL_PILE_ORDER}
    for book in books:
        pile, note = _physical_pile(s, book)
        piles[pile].append((book, note))

    for pile in _PHYSICAL_PILE_ORDER:
        entries = piles[pile]
        for start in range(0, len(entries), _DISCORD_MAX_ATTACHMENTS):
            batch = entries[start : start + _DISCORD_MAX_ATTACHMENTS]
            lines = [_PHYSICAL_PILE_TITLES[pile]] + [_review_book_line(book, note) for book, note in batch]
            files = []
            for book, _note in batch:
                cover = Path(book.folder_path) / "cover.jpg"
                if cover.exists():
                    files.append((f"{Path(book.folder_path).name}.jpg", cover.read_bytes(), "image/jpeg"))
            discord_notify.post_message("\n".join(lines), files=files or None)
    return len(books)


def _stock_book_line(book: Book) -> str:
    parts = [f"**{book.title or 'Sem título'}**"]
    if book.author:
        parts.append(book.author)
    if book.isbn:
        parts.append(f"ISBN {book.isbn}")
    parts.append(f"{book.price:.2f}€" if book.price is not None else "sem preço")
    parts.append(f"qtd {book.quantity}")
    parts.append("disponível" if book.status == "available" else "esgotado")
    return "- " + " · ".join(parts)


def send_stock_list_to_discord(s) -> int:
    """Posts the current stock (available + sold_out) as plain-text
    messages, batched to stay under Discord's per-message character limit.
    No photos - unlike the review sorting list, there's no "which physical
    book is this" ambiguity to solve here, every stocked book is already a
    confirmed, listed entry."""
    books = s.execute(select(Book).where(Book.status.in_(_VISIBLE_STATUSES)).order_by(Book.title)).scalars().all()
    header = f"📦 Stock atual — {len(books)} livro(s)"

    batches: list[list[str]] = []
    current: list[str] = []
    current_len = 0
    for book in books:
        line = _stock_book_line(book)
        if current and current_len + len(line) + 1 > _DISCORD_MAX_CONTENT:
            batches.append(current)
            current, current_len = [], 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        batches.append(current)

    if not batches:
        discord_notify.post_message(header)
        return 0

    for i, batch in enumerate(batches):
        prefix = header if i == 0 else f"📦 Stock atual (cont. {i + 1})"
        discord_notify.post_message("\n".join([prefix, *batch]))
    return len(books)


_STOCK_AUTHOR_TOP_N = 10


def _stock_breakdown(s) -> dict:
    books = s.execute(select(Book).where(Book.status.in_(_VISIBLE_STATUSES))).scalars().all()
    total = len(books)
    available = sum(1 for b in books if b.status == "available")
    sold_out = total - available

    def _pct(x):
        return round(x / total * 100, 1) if total else 0.0

    author_counts: dict[str, int] = {}
    for b in books:
        name = b.author or "Sem autor"
        author_counts[name] = author_counts.get(name, 0) + 1
    ranked = sorted(author_counts.items(), key=lambda kv: kv[1], reverse=True)
    top, rest = ranked[:_STOCK_AUTHOR_TOP_N], ranked[_STOCK_AUTHOR_TOP_N:]
    authors = [{"name": name, "count": count, "pct": _pct(count)} for name, count in top]
    others_count = sum(count for _, count in rest)
    if others_count:
        authors.append({"name": "Outros", "count": others_count, "pct": _pct(others_count)})

    return {
        "stock_available_count": available,
        "stock_sold_out_count": sold_out,
        "stock_available_pct": _pct(available),
        "stock_sold_out_pct": _pct(sold_out),
        "stock_authors": authors,
        # both views partition the same pool of books, so one tick width
        # serves both bars.
        "stock_unit_pct": round(100 / total, 4) if total else 0,
    }


def _reextract_one(s, book: Book) -> None:
    """Re-runs barcode+Almedina extraction for one book, applying the result
    (or lack of one) exactly like extract_pending_books does."""
    if settings.DEV_MODE:
        fields = _extract_with_dev_cache(s, Path(book.folder_path))
    else:
        fields = extract_book_fields(Path(book.folder_path))
    if fields["title"]:
        listing = compose_listing(fields)
        book.title = listing["title"]
        book.author = listing["author"]
        book.isbn = listing["isbn"]
        book.description = listing["description"]
        book.price = listing["price"]
        book.status = "pending"
    else:
        book.isbn = fields["isbn"]
        book.status = "failed"


def _run_bulk_reextract(book_ids: list[int]) -> None:
    """Runs in a background thread: re-extracts every given book, one at a
    time with the same pacing as extract_pending_books, publishing progress
    to _bulk_reextract_state as it goes so /reextract-all/status has
    something live to report."""
    total = len(book_ids)
    with _bulk_reextract_lock:
        _bulk_reextract_state.update(running=True, current=0, total=total, book_label=None)
    try:
        with db.SessionLocal() as s:
            for i, book_id in enumerate(book_ids):
                if i > 0:
                    time.sleep(random.uniform(2, 5))
                book = s.get(Book, book_id)
                if book is None:
                    continue
                with _bulk_reextract_lock:
                    _bulk_reextract_state.update(current=i + 1, book_label=book.title or Path(book.folder_path).name)
                _reextract_one(s, book)
                s.commit()
    finally:
        with _bulk_reextract_lock:
            _bulk_reextract_state["running"] = False


def _sidebar_counts(s) -> dict:
    raw_dir = Path(settings.RAW_DIR)
    raw_count = len([p for p in raw_dir.glob("*") if p.suffix.lower() in IMG_EXTS]) if raw_dir.exists() else 0
    sorted_count = s.execute(select(func.count()).select_from(Book).where(_SORTED_FILTER)).scalar_one()
    review_count = s.execute(select(func.count()).select_from(Book).where(_REVIEW_FILTER)).scalar_one()
    stock_count = s.execute(
        select(func.count()).select_from(Book).where(Book.status == "available")
    ).scalar_one()

    # For the header progress bar only: a raw pair is one book, a lone
    # unpaired leftover photo is half a book (it's not usable yet, but it's
    # not nothing either) - doesn't affect raw_count above, which stays a
    # plain image count for the sidebar badge.
    pairs, leftover = group_photos.propose_pairs()
    raw_units = len(pairs) + 0.5 * len(leftover)
    total_units = raw_units + sorted_count + review_count + stock_count

    def _pct(x):
        return round(x / total_units * 100, 1) if total_units else 0.0

    return {
        "raw_count": raw_count,
        "sorted_count": sorted_count,
        "review_count": review_count,
        "stock_count": stock_count,
        # book-equivalent count backing raw_pct (may be a half-integer, e.g.
        # "2.5") - shown alongside the percentage on hover; formatted to drop
        # a pointless trailing ".0" for whole numbers.
        "raw_units_display": f"{raw_units:g}",
        "raw_pct": _pct(raw_units),
        "sorted_pct": _pct(sorted_count),
        "review_pct": _pct(review_count),
        "stock_pct": _pct(stock_count),
        # width of one single book-unit, as a % of the whole bar - lets the
        # template draw a faint tick line per unit without dividing by zero
        # when there's nothing to show yet.
        "unit_pct": round(100 / total_units, 4) if total_units else 0,
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
def review_form(request: Request):
    with db.SessionLocal() as s:
        # Never-skipped books first (oldest by id), then skipped books
        # oldest-skip-first - a real FIFO carousel: "Passar por agora" (and,
        # in DEV_MODE, every Próximo click, since nothing is ever consumed
        # there) pushes a book behind everything else instead of just
        # showing it once and losing its place the moment you move on.
        book = s.execute(
            select(Book).where(_REVIEW_FILTER).order_by(Book.skipped_at.asc().nullsfirst(), Book.id.asc())
        ).scalars().first()
        duplicate_book = None
        if book is not None and not settings.DEV_MODE:
            duplicate_book = _find_isbn_duplicate(s, book)
        ctx = _sidebar_counts(s)
        breakdown = _review_queue_breakdown(s)
        return templates.TemplateResponse(
            request,
            "review.html",
            {**ctx, **breakdown, "active_step": "review", "book": book, "remaining": ctx["review_count"],
             "is_previous": False, "dev_mode": settings.DEV_MODE, "duplicate_book": duplicate_book},
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
    on_vinted: str | None = Form(None),
    on_olx: str | None = Form(None),
    on_marketplace: str | None = Form(None),
):
    on_vinted_flag = on_vinted is not None
    on_olx_flag = on_olx is not None
    on_marketplace_flag = on_marketplace is not None

    with db.SessionLocal() as s:
        book = s.get(Book, book_id)
        if book is None:
            raise HTTPException(404)
        book.isbn = isbn or None

        existing = None if settings.DEV_MODE else _find_isbn_duplicate(s, book)
        if existing is not None:
            # Same ISBN already stocked - fold this pending copy into that
            # listing (bump its quantity, refresh its fields) instead of
            # creating a second entry for the same book. Platform flags are
            # OR'd in rather than overwritten - if this copy is going on OLX
            # too, the existing listing is now on OLX too, not "just OLX".
            existing.title = title or None
            existing.author = author or None
            existing.description = description or None
            existing.price = price
            existing.quantity = existing.quantity + quantity
            existing.on_vinted = existing.on_vinted or on_vinted_flag
            existing.on_olx = existing.on_olx or on_olx_flag
            existing.on_marketplace = existing.on_marketplace or on_marketplace_flag
            existing.status = "available"
            s.delete(book)
            s.commit()
            return RedirectResponse("/review", status_code=303)

        book.title = title or None
        book.author = author or None
        book.description = description or None
        book.price = price
        book.quantity = quantity
        book.on_vinted = on_vinted_flag
        book.on_olx = on_olx_flag
        book.on_marketplace = on_marketplace_flag
        if settings.DEV_MODE:
            # Nothing is ever consumed in DEV_MODE, so "next" means the same
            # thing as a skip: push this book behind the rest of the queue
            # rather than showing it again immediately.
            book.skipped_at = datetime.now(timezone.utc)
        else:
            book.status = "available"
        s.commit()
    return RedirectResponse("/review", status_code=303)


@app.post("/skip/{book_id}")
def skip_book(book_id: int):
    """Passar por agora: leaves the book untouched, just deprioritized until
    the rest of the queue has cycled through - a real FIFO carousel, not a
    one-shot "show me the next one"."""
    with db.SessionLocal() as s:
        book = s.get(Book, book_id)
        if book is None:
            raise HTTPException(404)
        book.skipped_at = datetime.now(timezone.utc)
        s.commit()
    return RedirectResponse("/review", status_code=303)


@app.post("/review/delete/{book_id}")
def delete_review_book(book_id: int):
    """Elimina por completo um livro ainda na fila de confirmação: a pasta
    de fotos (cover.jpg + isbn.jpg) no disco e a entrada na base de dados -
    ao contrário de /delete (stock), que só remove a entrada e nunca deveria
    tocar em fotos de um livro já listado. Restrito a pending/failed por
    segurança: nunca deve apagar as fotos de um livro já em stock."""
    with db.SessionLocal() as s:
        book = s.get(Book, book_id)
        if book is None:
            raise HTTPException(404)
        if book.status not in ("pending", "failed"):
            raise HTTPException(400, "Este livro já não está na fila de confirmação.")
        folder = Path(book.folder_path)
        if folder.exists():
            shutil.rmtree(folder)
        s.delete(book)
        s.commit()
    return RedirectResponse("/review", status_code=303)


@app.post("/reextract/{book_id}")
def reextract_book(book_id: int):
    """Re-runs barcode+Almedina extraction for one book - for when a previous
    attempt decoded the wrong barcode or hit a transient Almedina failure."""
    with db.SessionLocal() as s:
        book = s.get(Book, book_id)
        if book is None:
            raise HTTPException(404)
        _reextract_one(s, book)
        s.commit()
    return RedirectResponse("/review", status_code=303)


@app.post("/reextract-all")
def reextract_all_books():
    """Procurar todos novamente: re-runs extraction for every book still
    waiting on confirmation (failed or already resolved), not just the one
    currently shown. Runs in a background thread, paced the same way
    extract_pending_books is, so the page can poll /reextract-all/status and
    show live progress instead of blocking on the full multi-book run."""
    with _bulk_reextract_lock:
        if _bulk_reextract_state["running"]:
            return {"started": False, "already_running": True}
    with db.SessionLocal() as s:
        book_ids = list(s.execute(select(Book.id).where(_REVIEW_FILTER)).scalars().all())
    threading.Thread(target=_run_bulk_reextract, args=(book_ids,), daemon=True).start()
    return {"started": True, "total": len(book_ids)}


@app.get("/reextract-all/status")
def reextract_all_status():
    with _bulk_reextract_lock:
        return dict(_bulk_reextract_state)


@app.post("/review/notify-discord")
def notify_discord_review():
    with db.SessionLocal() as s:
        try:
            sent = send_review_sort_list_to_discord(s)
        except discord_notify.DiscordNotifyError as e:
            return {"sent": False, "error": str(e)}
    return {"sent": True, "count": sent}


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
        duplicate_book = None if settings.DEV_MODE else _find_isbn_duplicate(s, book)
        ctx = _sidebar_counts(s)
        return templates.TemplateResponse(
            request,
            "review.html",
            {**ctx, "active_step": "review", "book": book, "remaining": None,
             "is_previous": True, "dev_mode": settings.DEV_MODE, "duplicate_book": duplicate_book},
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
        breakdown = _stock_breakdown(s)
        return templates.TemplateResponse(request, "available.html", {
            **ctx,
            **breakdown,
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


@app.post("/stock/notify-discord")
def notify_discord_stock():
    with db.SessionLocal() as s:
        try:
            sent = send_stock_list_to_discord(s)
        except discord_notify.DiscordNotifyError as e:
            return {"sent": False, "error": str(e)}
    return {"sent": True, "count": sent}


def _book_platform_codes(book: Book) -> list[str]:
    codes = []
    if book.on_vinted:
        codes.append("vinted")
    if book.on_olx:
        codes.append("olx")
    if book.on_marketplace:
        codes.append("marketplace")
    return codes


@app.post("/sold/{book_id}")
def mark_one_sold(book_id: int, platform: str = Form("")):
    with db.SessionLocal() as s:
        book = s.get(Book, book_id)
        if book is None:
            raise HTTPException(404)
        codes = _book_platform_codes(book)
        if len(codes) == 1:
            # Only ever posted in one place - no ambiguity, ignore whatever
            # (if anything) the client sent.
            sold_platform = codes[0]
        elif platform in codes:
            sold_platform = platform
        else:
            sold_platform = None
        s.add(Sale(book_id=book.id, title=book.title, isbn=book.isbn, price=book.price, platform=sold_platform))
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
    on_vinted: str | None = Form(None),
    on_olx: str | None = Form(None),
    on_marketplace: str | None = Form(None),
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
        book.on_vinted = on_vinted is not None
        book.on_olx = on_olx is not None
        book.on_marketplace = on_marketplace is not None
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


@app.post("/photo/{book_id}/{name}/rotate")
def rotate_photo(book_id: int, name: str):
    """Rotates cover.jpg/isbn.jpg 90° clockwise, in place on disk - not just
    a CSS transform, since dragging the image out of the browser into
    Vinted pulls the actual file bytes, not however this page happens to
    render it."""
    if name not in _PHOTO_NAMES:
        raise HTTPException(404)
    with db.SessionLocal() as s:
        book = s.get(Book, book_id)
        if book is None:
            raise HTTPException(404)
        path = Path(book.folder_path) / name
        if not path.exists():
            raise HTTPException(404)
    rotated = load_image_any(path).convert("RGB").rotate(-90, expand=True)
    rotated.save(path, "JPEG", quality=95)
    return {"rotated": True}
