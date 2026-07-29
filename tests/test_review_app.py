import os
import time

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from blt import review_app
from blt.models import Book, Sale
from blt.review_app import app

client = TestClient(app)


def _boom_if_called(*args, **kwargs):
    raise AssertionError("this should not have been called")


def _add_book(temp_db, **kwargs):
    kwargs.setdefault("folder_path", "book_x")
    kwargs.setdefault("status", "pending")
    with temp_db() as s:
        book = Book(**kwargs)
        s.add(book)
        s.commit()
        s.refresh(book)
        return book.id


def _make_photo(folder, name, taken_at, color=(1, 0, 0)):
    p = folder / name
    Image.new("RGB", (4, 4), color=color).save(p, "JPEG")
    os.utime(p, (taken_at, taken_at))
    return p


def _assert_color(actual, expected, tol=20):
    assert all(abs(a - e) <= tol for a, e in zip(actual, expected, strict=True)), f"{actual} != {expected} (tol={tol})"


# -------- Cross-origin write protection --------

def test_foreign_origin_is_rejected_on_a_write(temp_db):
    book_id = _add_book(temp_db, folder_path="book_csrf", status="available", quantity=1)

    r = client.post(f"/sold/{book_id}", headers={"Origin": "https://evil.example.com"})

    assert r.status_code == 403
    with temp_db() as s:
        assert s.get(Book, book_id).quantity == 1  # nothing happened


def test_foreign_referer_is_rejected_when_no_origin_sent(temp_db):
    book_id = _add_book(temp_db, folder_path="book_csrf2", status="available", quantity=1)

    r = client.post(f"/sold/{book_id}", headers={"Referer": "https://evil.example.com/attack.html"})

    assert r.status_code == 403
    with temp_db() as s:
        assert s.get(Book, book_id).quantity == 1


def test_matching_localhost_origin_is_allowed(temp_db):
    book_id = _add_book(temp_db, folder_path="book_csrf3", status="available", quantity=1)

    r = client.post(f"/sold/{book_id}", headers={"Origin": "http://127.0.0.1:8000"})

    assert r.status_code in (200, 303)
    with temp_db() as s:
        assert s.get(Book, book_id).quantity == 0


def test_missing_origin_and_referer_is_allowed(temp_db):
    """A non-browser client (curl, scripts) sends neither header - not the attack this guards against."""
    book_id = _add_book(temp_db, folder_path="book_csrf4", status="available", quantity=1)

    r = client.post(f"/sold/{book_id}")

    assert r.status_code in (200, 303)
    with temp_db() as s:
        assert s.get(Book, book_id).quantity == 0


def test_get_requests_are_never_blocked_by_origin_check(temp_db):
    r = client.get("/stock", headers={"Origin": "https://evil.example.com"})
    assert r.status_code == 200


# -------- Dashboard --------

def test_dashboard_shows_flow_with_all_four_steps(temp_db):
    r = client.get("/")

    assert r.status_code == 200
    assert "Imagens raw" in r.text
    assert "Imagens ordenadas" in r.text
    assert "Por confirmar" in r.text
    assert "Stock" in r.text


def test_sidebar_title_links_back_to_dashboard(temp_db):
    r = client.get("/stock")

    assert '<a class="sidebar-title" href="/">' in r.text
    assert '<img src="/static/icon.png" alt="blt - Book Listing Automation" class="sidebar-logo">' in r.text


def test_favicon_is_served_from_static(temp_db):
    r = client.get("/")
    assert '<link rel="icon" type="image/png" href="/static/icon.png">' in r.text

    icon = client.get("/static/icon.png")
    assert icon.status_code == 200
    assert icon.headers["content-type"] == "image/png"


def test_sidebar_badges_reflect_current_counts(monkeypatch, tmp_path, temp_db):
    raw = tmp_path / "raw"
    raw.mkdir()
    monkeypatch.setattr(review_app.settings, "RAW_DIR", str(raw))
    _make_photo(raw, "only.jpg", time.time())  # unpaired -> 1 raw image, 0 pairs

    _add_book(temp_db, folder_path="a", status="pending", title=None)  # sorted: 1
    _add_book(temp_db, folder_path="b", status="failed", isbn="1")  # review: 1
    _add_book(temp_db, folder_path="c", status="available", title="X")  # stock: 1

    r = client.get("/review")

    assert 'Imagens raw</span><span class="badge">1</span>' in r.text
    assert 'Imagens ordenadas</span><span class="badge">1</span>' in r.text
    assert 'Livros por confirmar</span><span class="badge">1</span>' in r.text
    assert 'Stock</span><span class="badge">1</span>' in r.text


def test_progress_header_weighs_a_leftover_photo_as_half_a_book(monkeypatch, tmp_path, temp_db):
    raw = tmp_path / "raw"
    raw.mkdir()
    monkeypatch.setattr(review_app.settings, "RAW_DIR", str(raw))
    _make_photo(raw, "only.jpg", time.time())  # 1 unpaired photo -> 0.5 raw book-units

    _add_book(temp_db, folder_path="a", status="pending", title="Resolved")  # review: 1 unit

    r = client.get("/review")

    # total = 0.5 + 1 = 1.5 -> raw 33.3%, review 66.7%
    assert 'title="Imagens raw: 0.5 (33.3%)"' in r.text
    assert 'title="Por confirmar: 1 (66.7%)"' in r.text


def test_progress_header_counts_a_complete_pair_as_one_full_book(monkeypatch, tmp_path, temp_db):
    raw = tmp_path / "raw"
    raw.mkdir()
    monkeypatch.setattr(review_app.settings, "RAW_DIR", str(raw))
    base = time.time()
    _make_photo(raw, "a.jpg", base)
    _make_photo(raw, "b.jpg", base + 1)  # 1 complete pair -> 1.0 raw book-unit, no leftover

    _add_book(temp_db, folder_path="x", status="pending", title="Resolved")  # review: 1 unit

    r = client.get("/review")

    # total = 1 + 1 = 2 -> 50/50
    assert 'title="Imagens raw: 1 (50.0%)"' in r.text
    assert 'title="Por confirmar: 1 (50.0%)"' in r.text


def test_progress_header_handles_zero_books_without_crashing(monkeypatch, tmp_path, temp_db):
    raw = tmp_path / "raw"
    raw.mkdir()
    monkeypatch.setattr(review_app.settings, "RAW_DIR", str(raw))

    r = client.get("/review")

    assert r.status_code == 200
    assert 'title="Imagens raw: 0 (0.0%)"' in r.text
    assert '<div class="progress-ticks"' not in r.text  # no units to mark, so no tick overlay element


def test_progress_bar_has_a_tick_per_unit_when_there_is_data(temp_db):
    _add_book(temp_db, folder_path="a", status="pending", title="Resolved")
    _add_book(temp_db, folder_path="b", status="pending", title="Resolved 2")

    r = client.get("/review")

    # 2 review units total -> each unit is 50% of the bar's width
    assert 'class="progress-ticks" style="background-size: 50.0% 100%;"' in r.text


def test_progress_header_present_on_every_page(temp_db):
    for path in ("/", "/raw", "/sorted", "/review", "/stock"):
        r = client.get(path)
        assert 'class="progress-block"' in r.text, f"missing on {path}"


def test_review_status_bar_breaks_down_the_queue_by_state(temp_db):
    _add_book(temp_db, folder_path="book_status_red", status="failed", isbn=None)
    _add_book(temp_db, folder_path="book_status_grey", status="failed", isbn="1")
    _add_book(
        temp_db, folder_path="book_status_stocked", status="available", title="Dup", isbn="2", quantity=1, price=7.0,
    )
    _add_book(temp_db, folder_path="book_status_yellow", status="pending", title="Dup", isbn="2", price=7.0)
    _add_book(temp_db, folder_path="book_status_green", status="pending", title="Unique", isbn="3", price=7.0)

    r = client.get("/review")

    # 4 books in the review queue (the stocked one isn't part of it): 1 each
    # of red/grey/yellow/green -> 25% apiece
    assert 'title="Sem ISBN: 1 (25.0%)"' in r.text
    assert 'title="Não encontrado: 1 (25.0%)"' in r.text
    assert 'title="Repetido: 1 (25.0%)"' in r.text
    assert 'title="Pronto: 1 (25.0%)"' in r.text
    # 4 books in the queue -> one tick mark every 25% of the bar's width
    assert '<div class="progress-ticks" style="background-size: 25.0% 100%;"></div>' in r.text


def test_review_status_bar_hidden_on_the_previous_page(temp_db):
    _add_book(temp_db, folder_path="book_status_prev", status="available", title="Prev")

    r = client.get("/previous")

    assert '<div class="stat-bar">' not in r.text


# -------- Raw images --------

def test_raw_page_shows_proposed_pairs_and_leftover(monkeypatch, tmp_path, temp_db):
    raw = tmp_path / "raw"
    raw.mkdir()
    monkeypatch.setattr(review_app.settings, "RAW_DIR", str(raw))
    base = time.time()
    _make_photo(raw, "a.jpg", base)
    _make_photo(raw, "b.jpg", base + 1)
    _make_photo(raw, "c.jpg", base + 2)  # leftover, odd count

    r = client.get("/raw")

    assert r.status_code == 200
    assert "1 par(es) proposto" in r.text
    assert "1 sem par" in r.text


def test_raw_photo_serves_file_from_raw_dir(monkeypatch, tmp_path, temp_db):
    raw = tmp_path / "raw"
    raw.mkdir()
    monkeypatch.setattr(review_app.settings, "RAW_DIR", str(raw))
    (raw / "x.jpg").write_bytes(b"fake-bytes")

    r = client.get("/raw-photo/x.jpg")

    assert r.status_code == 200
    assert r.content == b"fake-bytes"


def test_raw_photo_converts_heic_to_jpeg_for_display(monkeypatch, tmp_path, temp_db):
    """Phones shoot HEIC, but no desktop browser can render it in <img> - must convert for display."""
    raw = tmp_path / "raw"
    raw.mkdir()
    monkeypatch.setattr(review_app.settings, "RAW_DIR", str(raw))
    Image.new("RGB", (8, 8), color=(200, 0, 0)).save(raw / "x.heic", format="HEIF")

    r = client.get("/raw-photo/x.heic")

    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content[:2] == b"\xff\xd8"  # JPEG magic bytes, not HEIC's


def test_raw_photo_rejects_path_traversal(monkeypatch, tmp_path, temp_db):
    raw = tmp_path / "raw"
    raw.mkdir()
    monkeypatch.setattr(review_app.settings, "RAW_DIR", str(raw))
    (tmp_path / "secret.txt").write_bytes(b"nope")

    r = client.get("/raw-photo/..%2Fsecret.txt")

    assert r.status_code == 404


def test_raw_confirm_all_groups_and_registers_pending(monkeypatch, tmp_path, temp_db):
    raw = tmp_path / "raw"
    grouped = tmp_path / "grouped"
    raw.mkdir()
    monkeypatch.setattr(review_app.settings, "RAW_DIR", str(raw))
    monkeypatch.setattr(review_app.settings, "GROUPED_DIR", str(grouped))
    base = time.time()
    _make_photo(raw, "a.jpg", base)
    _make_photo(raw, "b.jpg", base + 1)

    r = client.post("/raw/confirm-all", follow_redirects=False)

    assert r.status_code == 303
    dest = grouped / "book_001"
    assert dest.exists()
    with temp_db() as s:
        book = s.execute(select(Book).where(Book.folder_path == str(dest))).scalar_one()
        assert book.status == "pending"


def test_raw_confirm_pair_uses_proposed_order_by_default(monkeypatch, tmp_path, temp_db):
    raw = tmp_path / "raw"
    grouped = tmp_path / "grouped"
    raw.mkdir()
    monkeypatch.setattr(review_app.settings, "RAW_DIR", str(raw))
    monkeypatch.setattr(review_app.settings, "GROUPED_DIR", str(grouped))
    _make_photo(raw, "a.jpg", time.time(), color=(10, 0, 0))
    _make_photo(raw, "b.jpg", time.time() + 1, color=(200, 0, 0))

    client.post("/raw/confirm-pair", data={"photo_a": "a.jpg", "photo_b": "b.jpg"})

    dest = grouped / "book_001"
    cover = Image.open(dest / "cover.jpg").convert("RGB").getpixel((0, 0))
    _assert_color(cover, (10, 0, 0))


def test_raw_confirm_pair_respects_swap(monkeypatch, tmp_path, temp_db):
    raw = tmp_path / "raw"
    grouped = tmp_path / "grouped"
    raw.mkdir()
    monkeypatch.setattr(review_app.settings, "RAW_DIR", str(raw))
    monkeypatch.setattr(review_app.settings, "GROUPED_DIR", str(grouped))
    _make_photo(raw, "a.jpg", time.time(), color=(10, 0, 0))
    _make_photo(raw, "b.jpg", time.time() + 1, color=(200, 0, 0))

    client.post("/raw/confirm-pair", data={"photo_a": "a.jpg", "photo_b": "b.jpg", "swap": "1"})

    dest = grouped / "book_001"
    cover = Image.open(dest / "cover.jpg").convert("RGB").getpixel((0, 0))
    _assert_color(cover, (200, 0, 0))  # swapped - b.jpg is now the cover


# -------- Sorted images --------

def test_sorted_page_lists_ungrouped_extracted_books(temp_db):
    _add_book(temp_db, folder_path="book_sorted", status="pending", title=None)

    r = client.get("/sorted")

    assert r.status_code == 200
    assert "1 livro" in r.text


def test_sorted_page_excludes_already_extracted_books(temp_db):
    _add_book(temp_db, folder_path="book_resolved", status="pending", title="Sempre Tu")
    _add_book(temp_db, folder_path="book_failed", status="failed")

    r = client.get("/sorted")

    assert "0 livro" in r.text


def test_sorted_detect_runs_extraction_and_redirects(monkeypatch, temp_db):
    calls = []
    monkeypatch.setattr(review_app, "extract_pending_books", lambda: calls.append(1))

    r = client.post("/sorted/detect", follow_redirects=False)

    assert r.status_code == 303
    assert r.headers["location"] == "/sorted"
    assert calls == [1]


# -------- Detected book waiting confirmation (/review) --------

def test_review_form_shows_nothing_left_when_no_books(temp_db):
    r = client.get("/review")
    assert r.status_code == 200
    assert "Não há livros por confirmar" in r.text


def test_review_form_shows_oldest_pending_book(temp_db):
    _add_book(temp_db, folder_path="book_001", title="Sempre Tu", isbn="9789896689704")

    r = client.get("/review")

    assert r.status_code == 200
    assert "Sempre Tu" in r.text
    assert "9789896689704" in r.text
    assert "1 livro" in r.text


def test_review_form_composes_sell_title_from_title_and_author(temp_db):
    _add_book(temp_db, folder_path="book_sell", title="Sempre Tu", author="Colleen Hoover")

    r = client.get("/review")

    assert 'id="sell_title" value="Sempre Tu - Colleen Hoover"' in r.text


def test_review_form_sell_title_omits_dash_when_no_author(temp_db):
    _add_book(temp_db, folder_path="book_no_author", title="Sempre Tu", author=None)

    r = client.get("/review")

    assert 'id="sell_title" value="Sempre Tu"' in r.text


def test_review_form_shows_description_before_isbn_before_title(temp_db):
    _add_book(temp_db, folder_path="book_order", title="Sempre Tu", author="Colleen Hoover", isbn="123")

    r = client.get("/review")

    assert r.text.index('id="description"') < r.text.index('id="isbn"') < r.text.index('id="title"')


def test_review_form_defaults_price_to_8_when_unset(temp_db):
    _add_book(temp_db, folder_path="book_no_price", status="failed", price=None)

    r = client.get("/review")

    assert 'id="price" name="price" type="number" step="0.01" min="0" class="no-native-spin" value="8.0"' in r.text


def test_review_form_price_has_custom_stepper_buttons(temp_db):
    _add_book(temp_db, folder_path="book_price_stepper", status="failed", price=7.98)

    r = client.get("/review")

    assert 'onclick="stepPrice(1)"' in r.text
    assert 'onclick="stepPrice(-1)"' in r.text


def test_review_form_shows_duplicate_warning_when_isbn_already_stocked(temp_db):
    _add_book(
        temp_db, folder_path="book_stocked", status="available", title="Already Here",
        isbn="555", quantity=1, price=7.0,
    )
    _add_book(temp_db, folder_path="book_pending_dup", status="pending", title="Already Here", isbn="555", price=7.0)

    r = client.get("/review")

    assert "já está em stock" in r.text
    assert '<button type="submit" form="review-form" class="warning">Adicionar <svg' in r.text


def test_review_form_has_no_duplicate_warning_for_a_unique_isbn(temp_db):
    _add_book(temp_db, folder_path="book_unique", status="pending", title="Unique Book", isbn="777", price=7.0)

    r = client.get("/review")

    assert "já está em stock" not in r.text
    assert '<button type="submit" form="review-form" class="primary">Criar <svg' in r.text


def test_dev_mode_review_form_never_shows_duplicate_warning(monkeypatch, temp_db):
    monkeypatch.setattr(review_app.settings, "DEV_MODE", True)
    _add_book(
        temp_db, folder_path="book_stocked_dev", status="available", title="Already Here",
        isbn="444", quantity=1, price=7.0,
    )
    _add_book(
        temp_db, folder_path="book_pending_dup_dev", status="pending", title="Already Here", isbn="444", price=7.0,
    )

    r = client.get("/review")

    assert "já está em stock" not in r.text  # DEV_MODE never merges, so never warns either


def test_sorted_book_does_not_appear_on_review_page(temp_db):
    _add_book(temp_db, folder_path="book_not_extracted", status="pending", title=None)

    r = client.get("/review")

    assert "Não há livros por confirmar" in r.text


def test_failed_book_shows_blank_title_but_keeps_isbn(temp_db):
    _add_book(temp_db, folder_path="book_002", status="failed", title=None, isbn="9789896689704")

    r = client.get("/review")

    assert r.status_code == 200
    assert "9789896689704" in r.text


def test_post_next_saves_fields_and_marks_available(temp_db):
    book_id = _add_book(temp_db, folder_path="book_003", title="Old", price=7.0)

    r = client.post(
        "/next",
        data={
            "book_id": book_id,
            "title": "New Title",
            "author": "New Author",
            "isbn": "9789896689704",
            "description": "desc",
            "price": "7.0",
            "quantity": "2",
        },
    )

    assert r.status_code == 200  # followed the redirect to /review
    with temp_db() as s:
        book = s.get(Book, book_id)
        assert book.title == "New Title"
        assert book.author == "New Author"
        assert book.quantity == 2
        assert book.status == "available"


def test_post_next_merges_into_existing_book_with_same_isbn(temp_db):
    existing_id = _add_book(
        temp_db, folder_path="book_existing", status="available", title="Old Title",
        isbn="9789896689704", quantity=2, price=7.0,
    )
    pending_id = _add_book(
        temp_db, folder_path="book_pending", status="pending", title="Sempre Tu",
        isbn="9789896689704", price=7.0,
    )

    r = client.post(
        "/next",
        data={
            "book_id": pending_id, "title": "Sempre Tu", "author": "Colleen Hoover",
            "isbn": "9789896689704", "description": "nova descricao", "price": "8.0", "quantity": "3",
        },
    )

    assert r.status_code == 200  # followed the redirect to /review
    with temp_db() as s:
        existing = s.get(Book, existing_id)
        assert existing.quantity == 5  # 2 already in stock + 3 just confirmed
        assert existing.title == "Sempre Tu"
        assert existing.author == "Colleen Hoover"
        assert existing.description == "nova descricao"
        assert existing.price == 8.0
        assert existing.status == "available"

        assert s.get(Book, pending_id) is None  # folded into the existing row, not kept as a second entry


def test_post_next_merge_reactivates_a_sold_out_book(temp_db):
    existing_id = _add_book(
        temp_db, folder_path="book_sold_out", status="sold_out", title="Old", isbn="123", quantity=0, price=7.0,
    )
    pending_id = _add_book(temp_db, folder_path="book_new_copy", status="pending", title="Old", isbn="123", price=7.0)

    client.post("/next", data={"book_id": pending_id, "title": "Old", "isbn": "123", "price": "7.0", "quantity": "2"})

    with temp_db() as s:
        existing = s.get(Book, existing_id)
        assert existing.quantity == 2
        assert existing.status == "available"  # new stock arrived - no longer sold out


def test_dev_mode_next_does_not_merge_duplicate_isbn(monkeypatch, temp_db):
    monkeypatch.setattr(review_app.settings, "DEV_MODE", True)
    existing_id = _add_book(
        temp_db, folder_path="book_existing_dev", status="available", title="Old", isbn="999", quantity=1, price=7.0,
    )
    pending_id = _add_book(
        temp_db, folder_path="book_pending_dev", status="pending", title="New", isbn="999", price=7.0,
    )

    client.post("/next", data={"book_id": pending_id, "title": "New", "isbn": "999", "price": "7.0", "quantity": "5"})

    with temp_db() as s:
        existing = s.get(Book, existing_id)
        assert existing.quantity == 1  # untouched - DEV_MODE never alters available/sold_out rows

        pending = s.get(Book, pending_id)
        assert pending is not None
        assert pending.status == "pending"  # DEV_MODE never promotes either


def test_next_advances_to_the_next_pending_book(temp_db):
    _add_book(temp_db, folder_path="book_a", title="First")
    _add_book(temp_db, folder_path="book_b", title="Second")

    with temp_db() as s:
        first_id = s.execute(select(Book).where(Book.folder_path == "book_a")).scalar_one().id

    client.post("/next", data={"book_id": first_id, "price": "7.0", "quantity": "1"})

    r = client.get("/review")
    assert "Second" in r.text
    assert "First" not in r.text


def test_skip_moves_to_the_next_book_without_touching_the_skipped_one(temp_db):
    first_id = _add_book(temp_db, folder_path="book_skip_a", title="First")
    _add_book(temp_db, folder_path="book_skip_b", title="Second")

    client.post(f"/skip/{first_id}")
    r = client.get("/review")

    assert "Second" in r.text
    with temp_db() as s:
        skipped = s.get(Book, first_id)
        assert skipped.status == "pending"  # untouched - still waiting in the queue
        assert skipped.title == "First"
        assert skipped.skipped_at is not None


def test_skip_is_a_real_carousel_survives_confirming_the_next_book(temp_db):
    """The actual bug being fixed: a one-shot ?after= cursor showed the next
    book once, but confirming *that* book reset the ordering back to plain
    id order - putting the skipped book right back on top immediately,
    instead of leaving it at the back until the rest of the queue cycles."""
    first_id = _add_book(temp_db, folder_path="book_carousel_a", title="First")
    second_id = _add_book(temp_db, folder_path="book_carousel_b", title="Second")
    _add_book(temp_db, folder_path="book_carousel_c", title="Third")

    client.post(f"/skip/{first_id}")
    client.post("/next", data={"book_id": second_id, "price": "8.0", "quantity": "1"})

    r = client.get("/review")
    assert "Third" in r.text  # not "First" - it's still deprioritized
    assert "First" not in r.text


def test_skip_twice_forms_a_fifo_queue_at_the_back(temp_db):
    first_id = _add_book(temp_db, folder_path="book_fifo_a", title="First")
    second_id = _add_book(temp_db, folder_path="book_fifo_b", title="Second")
    _add_book(temp_db, folder_path="book_fifo_c", title="Third")

    client.post(f"/skip/{first_id}")
    client.post(f"/skip/{second_id}")

    with temp_db() as s:
        ordered = s.execute(
            select(Book).where(review_app._REVIEW_FILTER)
            .order_by(Book.skipped_at.asc().nullsfirst(), Book.id.asc())
        ).scalars().all()
        assert [b.title for b in ordered] == ["Third", "First", "Second"]  # never-skipped first, then FIFO


def test_review_form_has_a_skip_link_pointing_at_the_current_book(temp_db):
    book_id = _add_book(temp_db, folder_path="book_skip_link", title="Skippable")

    r = client.get("/review")

    assert f'action="/skip/{book_id}"' in r.text
    assert '<button type="submit" class="info">Passar <svg' in r.text


def test_review_form_three_action_buttons_share_one_row_with_distinct_colors(temp_db):
    book_id = _add_book(temp_db, folder_path="book_action_row", title="Row", isbn="12345")

    r = client.get("/review")

    # all four live in the same .review-actions flex row, not split across
    # separate rows - the primary button is pulled out of #review-form via
    # the form="" attribute so it can sit alongside the others. Ordered
    # Eliminar -> Procurar -> Passar -> Criar/Adicionar (delete kept away
    # from the primary confirm button to reduce mis-click risk).
    actions_start = r.text.index('<div class="review-actions">')
    actions_end = r.text.index("</div>", actions_start)
    actions_html = r.text[actions_start:actions_end]
    eliminar_i = actions_html.index('class="danger">Eliminar <svg')
    procurar_i = actions_html.index('class="retry">Procurar <svg')
    passar_i = actions_html.index('class="info">Passar <svg')
    criar_i = actions_html.index('form="review-form" class="primary">Criar <svg')
    assert eliminar_i < procurar_i < passar_i < criar_i
    assert f'action="/reextract/{book_id}"' in r.text


def test_dev_mode_next_does_not_promote_saves_edits_and_stays_pending(monkeypatch, temp_db):
    monkeypatch.setattr(review_app.settings, "DEV_MODE", True)
    book_id = _add_book(temp_db, folder_path="book_dev", title="Old")

    client.post("/next", data={"book_id": book_id, "title": "Edited", "price": "7.0", "quantity": "1"})

    with temp_db() as s:
        book = s.get(Book, book_id)
        assert book.title == "Edited"  # edits are still saved
        assert book.status == "pending"  # but never promoted


def test_dev_mode_next_cycles_to_the_next_book(monkeypatch, temp_db):
    monkeypatch.setattr(review_app.settings, "DEV_MODE", True)
    first_id = _add_book(temp_db, folder_path="book_a", title="First")
    _add_book(temp_db, folder_path="book_b", title="Second")

    r = client.post("/next", data={"book_id": first_id, "price": "7.0", "quantity": "1"}, follow_redirects=True)

    assert "Second" in r.text
    with temp_db() as s:
        book = s.get(Book, first_id)
        assert book.status == "pending"  # book_a never left the queue
        assert book.skipped_at is not None  # pushed behind the rest, same as a manual skip


def test_dev_mode_wraps_around_after_the_last_book(monkeypatch, temp_db):
    monkeypatch.setattr(review_app.settings, "DEV_MODE", True)
    first_id = _add_book(temp_db, folder_path="book_a", title="First")
    second_id = _add_book(temp_db, folder_path="book_b", title="Second")

    client.post("/next", data={"book_id": first_id, "title": "First", "price": "7.0", "quantity": "1"})
    r = client.post(
        "/next", data={"book_id": second_id, "title": "Second", "price": "7.0", "quantity": "1"},
        follow_redirects=True,
    )

    assert "First" in r.text  # wrapped back to the start, nothing lost


def test_dev_mode_shows_a_badge_on_the_review_page(monkeypatch, temp_db):
    monkeypatch.setattr(review_app.settings, "DEV_MODE", True)
    _add_book(temp_db, folder_path="book_dev", title="Something")

    r = client.get("/review")

    assert "DEV MODE" in r.text


def test_prod_mode_shows_no_dev_badge(temp_db):
    _add_book(temp_db, folder_path="book_prod", title="Something")

    r = client.get("/review")

    assert "DEV MODE" not in r.text


def test_previous_returns_404_when_nothing_available_yet(temp_db):
    r = client.get("/previous")
    assert r.status_code == 404


def test_previous_shows_most_recently_updated_available_book(temp_db):
    _add_book(temp_db, folder_path="book_older", status="available", title="Older")
    _add_book(temp_db, folder_path="book_newer", status="available", title="Newer")

    r = client.get("/previous")

    assert r.status_code == 200
    assert "Newer" in r.text


def test_revert_sends_book_back_to_pending(temp_db):
    book_id = _add_book(temp_db, folder_path="book_oops", status="available", title="Oops")

    client.post(f"/revert/{book_id}")

    with temp_db() as s:
        book = s.get(Book, book_id)
        assert book.status == "pending"

    r = client.get("/review")
    assert "Oops" in r.text


def test_reextract_resolves_and_flips_failed_to_pending(monkeypatch, temp_db):
    book_id = _add_book(temp_db, folder_path="book_retry", status="failed", isbn="9789896689704")
    monkeypatch.setattr(
        review_app, "extract_book_fields",
        lambda folder: {"title": "Sempre Tu", "author": "Colleen Hoover", "isbn": "9789896689704"},
    )

    client.post(f"/reextract/{book_id}")

    with temp_db() as s:
        book = s.get(Book, book_id)
        assert book.title == "Sempre Tu"
        assert book.author == "Colleen Hoover"
        assert book.description
        assert book.status == "pending"  # resolved now, no longer needs manual entry


def test_reextract_keeps_failed_status_when_still_unresolved(monkeypatch, temp_db):
    book_id = _add_book(temp_db, folder_path="book_retry_fail", status="failed", isbn="000")
    monkeypatch.setattr(
        review_app, "extract_book_fields", lambda folder: {"title": None, "author": None, "isbn": "111"},
    )

    client.post(f"/reextract/{book_id}")

    with temp_db() as s:
        book = s.get(Book, book_id)
        assert book.status == "failed"
        assert book.isbn == "111"  # updated to whatever this attempt decoded


def test_reextract_uses_dev_cache_in_dev_mode(monkeypatch, temp_db):
    monkeypatch.setattr(review_app.settings, "DEV_MODE", True)
    book_id = _add_book(temp_db, folder_path="book_retry_dev", status="failed", isbn="222")
    monkeypatch.setattr(review_app, "extract_book_fields", _boom_if_called)
    monkeypatch.setattr(
        review_app, "_extract_with_dev_cache",
        lambda s, folder: {"title": "Cached Title", "author": None, "isbn": "222"},
    )

    client.post(f"/reextract/{book_id}")

    with temp_db() as s:
        assert s.get(Book, book_id).title == "Cached Title"


def test_review_form_reextract_button_shown_only_when_isbn_present(temp_db):
    _add_book(temp_db, folder_path="book_has_isbn", status="failed", isbn="333")

    r = client.get("/review")

    assert 'action="/reextract/' in r.text


def test_review_form_reextract_button_hidden_without_isbn(temp_db):
    _add_book(temp_db, folder_path="book_no_isbn", status="failed", isbn=None)

    r = client.get("/review")

    assert 'action="/reextract/' not in r.text


class _SyncThread:
    """Stand-in for threading.Thread that runs the target immediately, in the
    calling thread, instead of really threading - makes the background bulk
    reextract job deterministic and synchronous under test."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


def _reset_bulk_state():
    review_app._bulk_reextract_state.update(running=False, current=0, total=0, book_label=None)


def test_reextract_all_resolves_every_book_in_the_queue(monkeypatch, temp_db):
    _reset_bulk_state()
    a_id = _add_book(temp_db, folder_path="book_bulk_a", status="failed", isbn="1")
    b_id = _add_book(temp_db, folder_path="book_bulk_b", status="failed", isbn="2")
    monkeypatch.setattr(review_app.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(review_app.threading, "Thread", _SyncThread)
    monkeypatch.setattr(
        review_app, "extract_book_fields",
        lambda folder: {"title": f"Resolved {folder}", "author": None, "isbn": "999"},
    )

    client.post("/reextract-all")

    with temp_db() as s:
        assert s.get(Book, a_id).status == "pending"
        assert s.get(Book, b_id).status == "pending"
        assert s.get(Book, a_id).title.startswith("Resolved")
        assert s.get(Book, b_id).title.startswith("Resolved")


def test_reextract_all_paces_requests_between_books_not_before_the_first(monkeypatch, temp_db):
    _reset_bulk_state()
    _add_book(temp_db, folder_path="book_bulk_c", status="failed", isbn="1")
    _add_book(temp_db, folder_path="book_bulk_d", status="failed", isbn="2")
    _add_book(temp_db, folder_path="book_bulk_e", status="failed", isbn="3")
    sleep_calls = []
    monkeypatch.setattr(review_app.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr(review_app.threading, "Thread", _SyncThread)
    monkeypatch.setattr(review_app, "extract_book_fields", lambda folder: {"title": None, "author": None, "isbn": None})

    client.post("/reextract-all")

    assert len(sleep_calls) == 2  # paced between books, but not before the first one


def test_reextract_all_uses_dev_cache_in_dev_mode(monkeypatch, temp_db):
    _reset_bulk_state()
    monkeypatch.setattr(review_app.settings, "DEV_MODE", True)
    book_id = _add_book(temp_db, folder_path="book_bulk_dev", status="failed", isbn="1")
    monkeypatch.setattr(review_app, "extract_book_fields", _boom_if_called)
    monkeypatch.setattr(review_app.threading, "Thread", _SyncThread)
    monkeypatch.setattr(
        review_app, "_extract_with_dev_cache",
        lambda s, folder: {"title": "Cached", "author": None, "isbn": "1"},
    )

    client.post("/reextract-all")

    with temp_db() as s:
        assert s.get(Book, book_id).title == "Cached"


def test_reextract_all_returns_started_and_total_as_json(monkeypatch, temp_db):
    _reset_bulk_state()
    _add_book(temp_db, folder_path="book_bulk_f", status="failed", isbn="1")
    _add_book(temp_db, folder_path="book_bulk_g", status="failed", isbn="2")
    monkeypatch.setattr(review_app.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(review_app.threading, "Thread", _SyncThread)
    monkeypatch.setattr(review_app, "extract_book_fields", lambda folder: {"title": None, "author": None, "isbn": None})

    r = client.post("/reextract-all")

    assert r.json() == {"started": True, "total": 2}


def test_reextract_all_does_not_start_a_second_run_while_one_is_in_progress(monkeypatch, temp_db):
    _reset_bulk_state()
    _add_book(temp_db, folder_path="book_bulk_h", status="failed", isbn="1")
    review_app._bulk_reextract_state.update(running=True, current=1, total=3, book_label="Alguma coisa")
    monkeypatch.setattr(review_app.threading, "Thread", lambda *a, **k: _boom_if_called())

    r = client.post("/reextract-all")

    assert r.json() == {"started": False, "already_running": True}


def test_reextract_all_status_reports_progress_per_book(monkeypatch, temp_db):
    _reset_bulk_state()
    _add_book(temp_db, folder_path="book_bulk_i", status="failed", isbn="1")
    _add_book(temp_db, folder_path="book_bulk_j", status="failed", isbn="2")
    monkeypatch.setattr(review_app.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(review_app.threading, "Thread", _SyncThread)
    snapshots = []

    def fake_reextract_one(s, book):
        snapshots.append(dict(review_app._bulk_reextract_state))
        book.title = f"Resolved {book.folder_path}"
        book.status = "pending"

    monkeypatch.setattr(review_app, "_reextract_one", fake_reextract_one)

    client.post("/reextract-all")

    assert [snap["current"] for snap in snapshots] == [1, 2]
    assert all(snap["total"] == 2 for snap in snapshots)
    assert all(snap["running"] for snap in snapshots)
    assert review_app._bulk_reextract_state["running"] is False


def test_reextract_all_status_endpoint_returns_current_state(monkeypatch, temp_db):
    _reset_bulk_state()
    review_app._bulk_reextract_state.update(running=True, current=2, total=5, book_label="A Villa")

    r = client.get("/reextract-all/status")

    assert r.json() == {"running": True, "current": 2, "total": 5, "book_label": "A Villa"}


def test_review_form_has_a_reextract_all_button(temp_db):
    _add_book(temp_db, folder_path="book_bulk_button", status="failed", isbn="1")

    r = client.get("/review")

    assert 'id="reextract-all-btn"' in r.text
    assert "procurar todos novamente" in r.text


# -------- Stock --------

def test_stock_bar_status_tab_shows_available_vs_sold_out(temp_db):
    _add_book(temp_db, folder_path="book_bar_avail1", status="available", title="A")
    _add_book(temp_db, folder_path="book_bar_avail2", status="available", title="B")
    _add_book(temp_db, folder_path="book_bar_sold", status="sold_out", title="C", quantity=0)

    r = client.get("/stock")

    assert 'title="Disponível: 2 (66.7%)"' in r.text
    assert 'title="Esgotado: 1 (33.3%)"' in r.text
    # status tab shown by default, author tab hidden
    assert '<div id="stock-tab-status">' in r.text
    assert '<div id="stock-tab-author" style="display: none;">' in r.text


def test_stock_bar_author_tab_ranks_authors_and_groups_the_rest_as_outros(temp_db):
    for i in range(11):
        _add_book(
            temp_db, folder_path=f"book_author_{i}", status="available", title=f"Book {i}",
            author=f"Author {i}",
        )
    # give "Author 0" a second book so it's unambiguously the top author
    _add_book(temp_db, folder_path="book_author_0_extra", status="available", title="Extra", author="Author 0")

    r = client.get("/stock")

    assert 'title="Author 0: 2 (16.7%)"' in r.text
    # 10 named authors max - the 11th (single-book) author folds into Outros
    assert 'title="Outros: 1 (8.3%)"' in r.text


def test_stock_bar_groups_missing_author_as_sem_autor(temp_db):
    _add_book(temp_db, folder_path="book_no_author", status="available", title="X", author=None)

    r = client.get("/stock")

    assert 'title="Sem autor: 1 (100.0%)"' in r.text


def test_stock_bar_has_tick_marks_and_tab_buttons(temp_db):
    _add_book(temp_db, folder_path="book_tick_a", status="available", title="A")
    _add_book(temp_db, folder_path="book_tick_b", status="available", title="B")

    r = client.get("/stock")

    assert '<div class="progress-ticks" style="background-size: 50.0% 100%;"></div>' in r.text
    assert 'onclick="showStockTab(\'status\', this)"' in r.text
    assert 'onclick="showStockTab(\'author\', this)"' in r.text


def test_all_three_progress_bars_have_a_visible_title(temp_db):
    _add_book(temp_db, folder_path="book_title_check", status="available", title="X")

    assert '<h3 class="bar-title">Progresso</h3>' in client.get("/").text
    assert '<h3 class="bar-title">Estado da fila de confirmação</h3>' in client.get("/review").text
    assert '<h3 class="bar-title">Estado do stock</h3>' in client.get("/stock").text


def test_stock_list_shows_available_books(temp_db):
    _add_book(temp_db, folder_path="book_avail", title="Available Book", status="available", quantity=3)

    r = client.get("/stock")

    assert r.status_code == 200
    assert "Available Book" in r.text
    assert ">3<" in r.text


def test_stock_search_matches_title_isbn_or_author(temp_db):
    _add_book(temp_db, folder_path="a", status="available", title="Sempre Tu", isbn="111", author="Colleen Hoover")
    _add_book(temp_db, folder_path="b", status="available", title="Outro Livro", isbn="9789896689704", author="Autor B")
    _add_book(temp_db, folder_path="c", status="available", title="Terceiro", isbn="333", author="Autor C")

    by_title = client.get("/stock", params={"q": "Sempre"}).text
    by_isbn = client.get("/stock", params={"q": "9789896689704"}).text
    by_author = client.get("/stock", params={"q": "Autor C"}).text

    assert "Sempre Tu" in by_title and "Outro Livro" not in by_title
    assert "Outro Livro" in by_isbn and "Sempre Tu" not in by_isbn
    assert "Terceiro" in by_author and "Sempre Tu" not in by_author


def test_stock_sort_by_price_ascending_and_descending(temp_db):
    _add_book(temp_db, folder_path="cheap", status="available", title="Cheap", price=3.0)
    _add_book(temp_db, folder_path="mid", status="available", title="Mid", price=7.0)
    _add_book(temp_db, folder_path="expensive", status="available", title="Expensive", price=12.0)

    asc = client.get("/stock", params={"sort": "price", "dir": "asc"}).text
    desc = client.get("/stock", params={"sort": "price", "dir": "desc"}).text

    assert asc.index("Cheap") < asc.index("Mid") < asc.index("Expensive")
    assert desc.index("Expensive") < desc.index("Mid") < desc.index("Cheap")


def test_stock_default_pagination_is_20_per_page(temp_db):
    with temp_db() as s:
        for i in range(25):
            s.add(Book(folder_path=f"book_{i}", status="available", title=f"Title {i:02d}"))
        s.commit()

    r = client.get("/stock")

    assert "Página 1 de 2" in r.text
    assert r.text.count("Marcar 1 vendido") == 20


def test_stock_view_all_shows_everything_without_pagination(temp_db):
    with temp_db() as s:
        for i in range(25):
            s.add(Book(folder_path=f"book_{i}", status="available", title=f"Title {i:02d}"))
        s.commit()

    r = client.get("/stock", params={"view": "all"})

    assert r.text.count("Marcar 1 vendido") == 25
    assert "Página" not in r.text


def test_delete_removes_available_book(temp_db):
    book_id = _add_book(temp_db, folder_path="book_del_avail", status="available", title="Gone Soon")

    r = client.post(f"/delete/{book_id}", follow_redirects=False)

    assert r.status_code == 303
    assert r.headers["location"] == "/stock"
    with temp_db() as s:
        assert s.get(Book, book_id) is None


def test_delete_removes_sold_out_book(temp_db):
    book_id = _add_book(temp_db, folder_path="book_del_sold", status="sold_out", quantity=0, title="Gone")

    client.post(f"/delete/{book_id}")

    with temp_db() as s:
        assert s.get(Book, book_id) is None


def test_delete_unknown_book_404s(temp_db):
    r = client.post("/delete/999999")
    assert r.status_code == 404


def test_review_delete_removes_folder_and_db_row(temp_db, tmp_path):
    folder = tmp_path / "book_review_del"
    folder.mkdir()
    (folder / "cover.jpg").write_bytes(b"fake-cover")
    (folder / "isbn.jpg").write_bytes(b"fake-isbn")
    book_id = _add_book(temp_db, folder_path=str(folder), status="failed", isbn="1")

    r = client.post(f"/review/delete/{book_id}", follow_redirects=False)

    assert r.status_code == 303
    assert r.headers["location"] == "/review"
    assert not folder.exists()
    with temp_db() as s:
        assert s.get(Book, book_id) is None


def test_review_delete_works_on_pending_books_too(temp_db, tmp_path):
    folder = tmp_path / "book_review_del_pending"
    folder.mkdir()
    book_id = _add_book(temp_db, folder_path=str(folder), status="pending", title="Resolved but unconfirmed")

    client.post(f"/review/delete/{book_id}")

    with temp_db() as s:
        assert s.get(Book, book_id) is None


def test_review_delete_handles_missing_folder_gracefully(temp_db, tmp_path):
    missing_folder = tmp_path / "already_gone"
    book_id = _add_book(temp_db, folder_path=str(missing_folder), status="failed", isbn=None)

    r = client.post(f"/review/delete/{book_id}")

    assert r.status_code in (200, 303)
    with temp_db() as s:
        assert s.get(Book, book_id) is None


def test_review_delete_unknown_book_404s(temp_db):
    r = client.post("/review/delete/999999")
    assert r.status_code == 404


def test_review_delete_rejects_books_already_in_stock(temp_db, tmp_path):
    folder = tmp_path / "book_already_available"
    folder.mkdir()
    (folder / "cover.jpg").write_bytes(b"fake-cover")
    book_id = _add_book(temp_db, folder_path=str(folder), status="available", title="Já Listado")

    r = client.post(f"/review/delete/{book_id}")

    assert r.status_code == 400
    assert folder.exists()  # photos of a real listing are never touched
    with temp_db() as s:
        assert s.get(Book, book_id) is not None


def test_review_form_has_a_delete_button_with_confirm(temp_db):
    book_id = _add_book(temp_db, folder_path="book_review_del_ui", status="failed", isbn="1")

    r = client.get("/review")

    assert f'action="/review/delete/{book_id}"' in r.text
    assert '<button type="submit" class="danger">Eliminar <svg' in r.text
    assert "Não pode ser desfeito" in r.text


def test_stock_page_has_a_delete_button_per_row(temp_db):
    book_id = _add_book(temp_db, folder_path="book_del_ui", status="available", title="Delete Me")

    r = client.get("/stock")

    assert f'action="/delete/{book_id}"' in r.text


def test_mark_sold_records_a_sale_snapshot(temp_db):
    book_id = _add_book(temp_db, folder_path="book_sale", status="available", quantity=2,
                         title="Sempre Tu", isbn="9789896689704", price=8.5)

    client.post(f"/sold/{book_id}")

    with temp_db() as s:
        sale = s.execute(select(Sale)).scalar_one()
        assert sale.book_id == book_id
        assert sale.title == "Sempre Tu"
        assert sale.isbn == "9789896689704"
        assert sale.price == 8.5


def test_sale_survives_book_deletion(temp_db):
    book_id = _add_book(
        temp_db, folder_path="book_sale_del", status="available", quantity=1, title="Gone Later", price=7.0,
    )

    client.post(f"/sold/{book_id}")  # quantity 1 -> 0, status becomes sold_out
    client.post(f"/delete/{book_id}")

    with temp_db() as s:
        assert s.get(Book, book_id) is None  # book itself is gone
        sale = s.execute(select(Sale)).scalar_one()
        assert sale.title == "Gone Later"  # sale record's own snapshot is untouched
        assert sale.price == 7.0


def test_stock_edit_saves_all_fields(temp_db):
    book_id = _add_book(temp_db, folder_path="book_reprice", status="available",
                         title="Old Title", author="Old Author", isbn="000", price=7.0, quantity=1)

    r = client.post(f"/stock/edit/{book_id}", data={
        "title": "New Title", "author": "New Author", "isbn": "9789896689704",
        "price": "9.5", "quantity": "3",
    }, follow_redirects=False)

    assert r.status_code == 303
    assert r.headers["location"] == "/stock"
    with temp_db() as s:
        book = s.get(Book, book_id)
        assert book.title == "New Title"
        assert book.author == "New Author"
        assert book.isbn == "9789896689704"
        assert book.price == 9.5
        assert book.quantity == 3
        assert book.status == "available"


def test_stock_edit_setting_quantity_to_zero_marks_sold_out(temp_db):
    book_id = _add_book(temp_db, folder_path="book_zero", status="available", price=7.0, quantity=2)

    client.post(f"/stock/edit/{book_id}", data={"price": "7.0", "quantity": "0"})

    with temp_db() as s:
        book = s.get(Book, book_id)
        assert book.quantity == 0
        assert book.status == "sold_out"


def test_stock_edit_unknown_book_404s(temp_db):
    r = client.post("/stock/edit/999999", data={"price": "9.5", "quantity": "1"})
    assert r.status_code == 404


def test_stock_page_has_edit_button_and_hidden_edit_row_with_all_fields(temp_db):
    book_id = _add_book(temp_db, folder_path="book_editar", status="available", price=7.0)

    r = client.get("/stock")

    assert f"toggleEdit({book_id})" in r.text
    assert f'id="edit-row-{book_id}"' in r.text
    assert f'action="/stock/edit/{book_id}"' in r.text
    assert f'id="edit-title-{book_id}"' in r.text
    assert f'id="edit-author-{book_id}"' in r.text
    assert f'id="edit-isbn-{book_id}"' in r.text
    assert f'id="edit-quantity-{book_id}"' in r.text


def test_stock_edit_save_and_discard_buttons_start_disabled_until_a_field_changes(temp_db):
    book_id = _add_book(temp_db, folder_path="book_dirty", status="available", price=7.0)

    r = client.get("/stock")

    save_btn = f'id="save-btn-{book_id}" title="Guardar" disabled'
    discard_btn = f'id="discard-btn-{book_id}" title="Descartar" disabled'
    assert save_btn in r.text
    assert discard_btn in r.text
    assert f"markDirty({book_id})" in r.text  # wired on the editable fields


def test_dashboard_shows_total_revenue_and_sold_count(temp_db):
    book_id = _add_book(temp_db, folder_path="book_rev", status="available", quantity=1, price=10.0)
    client.post(f"/sold/{book_id}")

    r = client.get("/")

    assert "10.00" in r.text
    assert "Receita total" in r.text
    assert "Livros vendidos" in r.text


def test_dashboard_weekly_sales_table_reflects_a_real_sale(temp_db):
    book_id = _add_book(temp_db, folder_path="book_weekly", status="available", quantity=1, price=12.5)
    client.post(f"/sold/{book_id}")

    r = client.get("/")

    assert "Vendas por semana" in r.text
    assert "12.50" in r.text


def test_mark_sold_decrements_quantity(temp_db):
    book_id = _add_book(temp_db, folder_path="book_stock", status="available", quantity=2)

    client.post(f"/sold/{book_id}")

    with temp_db() as s:
        book = s.get(Book, book_id)
        assert book.quantity == 1
        assert book.status == "available"


def test_mark_sold_flips_to_sold_out_at_zero(temp_db):
    book_id = _add_book(temp_db, folder_path="book_last", status="available", quantity=1, title="Last Copy")

    client.post(f"/sold/{book_id}")

    with temp_db() as s:
        book = s.get(Book, book_id)
        assert book.quantity == 0
        assert book.status == "sold_out"

    r = client.get("/stock")
    assert "Last Copy" in r.text  # stays visible, just marked sold out
    assert "Esgotado" in r.text
    assert "Marcar 1 vendido" not in r.text  # no sell button left for a sold-out book


def test_sold_out_book_stays_visible_marked_unsellable_and_sorted_last(temp_db):
    _add_book(temp_db, folder_path="book_gone", status="sold_out", quantity=0, title="Gone")
    _add_book(temp_db, folder_path="book_here", status="available", quantity=1, title="Zzz Still Here")

    r = client.get("/stock")

    assert "Gone" in r.text
    assert "Esgotado" in r.text
    # sold-out sorts after available even though "Gone" < "Zzz..." alphabetically
    assert r.text.index("Zzz Still Here") < r.text.index("Gone")


# -------- Discord notifications --------

def _make_cover(folder, data=b"fake-jpeg-bytes"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "cover.jpg").write_bytes(data)


def _capture_post_message(monkeypatch):
    """Replaces discord_notify.post_message with a recorder and returns the
    list of (content, files) tuples it was called with."""
    calls = []

    def record(content, files=None):
        calls.append((content, files))

    monkeypatch.setattr(review_app.discord_notify, "post_message", record)
    return calls


def test_send_review_sort_list_groups_into_three_physical_piles(monkeypatch, temp_db, tmp_path):
    calls = _capture_post_message(monkeypatch)

    foto_folder = tmp_path / "book_foto"
    _make_cover(foto_folder)
    _add_book(temp_db, folder_path=str(foto_folder), status="failed", isbn=None)

    manual_folder = tmp_path / "book_manual"
    _make_cover(manual_folder)
    _add_book(temp_db, folder_path=str(manual_folder), status="failed", isbn="9789896689704")

    vender_folder = tmp_path / "book_vender"
    _make_cover(vender_folder)
    _add_book(
        temp_db, folder_path=str(vender_folder), status="pending",
        isbn="9789896689705", title="Pronto", author="Alguém",
    )

    with temp_db() as s:
        sent = review_app.send_review_sort_list_to_discord(s)

    assert sent == 3
    assert len(calls) == 3  # one message per non-empty pile
    contents = [content for content, _files in calls]
    assert any("Tirar nova foto" in c and "book_foto" in c for c in contents)
    assert any("Inserir à mão" in c and "book_manual" in c for c in contents)
    assert any("Pronto para vender" in c and "book_vender" in c and "Pronto" in c for c in contents)
    # each message attaches the cover photo of every book it lists
    assert all(files and len(files) == 1 for _content, files in calls)


def test_send_review_sort_list_notes_duplicates_as_will_merge(monkeypatch, temp_db, tmp_path):
    calls = _capture_post_message(monkeypatch)
    _add_book(
        temp_db, folder_path="book_existing_stock", status="available",
        isbn="9789896689704", title="Já em Stock",
    )
    dup_folder = tmp_path / "book_dup"
    _make_cover(dup_folder)
    _add_book(temp_db, folder_path=str(dup_folder), status="pending", isbn="9789896689704", title="Já em Stock")

    with temp_db() as s:
        review_app.send_review_sort_list_to_discord(s)

    sell_message = next(content for content, _files in calls if "Pronto para vender" in content)
    assert "já em stock" in sell_message


def test_send_review_sort_list_batches_over_ten_attachments_per_message(monkeypatch, temp_db, tmp_path):
    calls = _capture_post_message(monkeypatch)
    for i in range(12):
        folder = tmp_path / f"book_{i}"
        _make_cover(folder)
        _add_book(
            temp_db, folder_path=str(folder), status="pending",
            isbn=f"978989668970{i % 10}", title=f"Livro {i}",
        )

    with temp_db() as s:
        sent = review_app.send_review_sort_list_to_discord(s)

    assert sent == 12
    sell_messages = [files for content, files in calls if "Pronto para vender" in content]
    assert len(sell_messages) == 2  # 12 books split into batches of 10 + 2
    assert len(sell_messages[0]) == 10
    assert len(sell_messages[1]) == 2


def test_send_review_sort_list_skips_attachment_when_cover_missing(monkeypatch, temp_db):
    calls = _capture_post_message(monkeypatch)
    _add_book(temp_db, folder_path="book_no_cover_on_disk", status="failed", isbn=None)

    with temp_db() as s:
        review_app.send_review_sort_list_to_discord(s)

    content, files = calls[0]
    assert "book_no_cover_on_disk" in content
    assert files is None


def test_send_review_sort_list_empty_queue_sends_nothing(monkeypatch, temp_db):
    monkeypatch.setattr(review_app.discord_notify, "post_message", _boom_if_called)

    with temp_db() as s:
        sent = review_app.send_review_sort_list_to_discord(s)

    assert sent == 0


def test_send_stock_list_reports_every_visible_book(monkeypatch, temp_db):
    calls = _capture_post_message(monkeypatch)
    _add_book(
        temp_db, folder_path="book_a", status="available", title="Livro A", author="Autora A",
        isbn="9789896689704", price=9.5, quantity=2,
    )
    _add_book(
        temp_db, folder_path="book_b", status="sold_out", title="Livro B", author="Autor B",
        isbn="9789896689705", price=7.0, quantity=0,
    )

    with temp_db() as s:
        sent = review_app.send_stock_list_to_discord(s)

    assert sent == 2
    assert len(calls) == 1
    content = calls[0][0]
    assert "Livro A" in content and "disponível" in content
    assert "Livro B" in content and "esgotado" in content


def test_send_stock_list_empty_stock_still_posts_a_header(monkeypatch, temp_db):
    calls = _capture_post_message(monkeypatch)

    with temp_db() as s:
        sent = review_app.send_stock_list_to_discord(s)

    assert sent == 0
    assert len(calls) == 1
    assert "Stock atual" in calls[0][0]


def test_send_stock_list_batches_when_content_exceeds_the_limit(monkeypatch, temp_db):
    monkeypatch.setattr(review_app, "_DISCORD_MAX_CONTENT", 50)
    calls = _capture_post_message(monkeypatch)
    for i in range(5):
        _add_book(
            temp_db, folder_path=f"book_{i}", status="available",
            title=f"Um Título Razoavelmente Longo {i}", quantity=1,
        )

    with temp_db() as s:
        sent = review_app.send_stock_list_to_discord(s)

    assert sent == 5
    assert len(calls) > 1


def test_notify_discord_review_endpoint_reports_success(monkeypatch, temp_db):
    monkeypatch.setattr(review_app, "send_review_sort_list_to_discord", lambda s: 4)

    r = client.post("/review/notify-discord")

    assert r.json() == {"sent": True, "count": 4}


def test_notify_discord_review_endpoint_reports_error(monkeypatch, temp_db):
    def raise_error(s):
        raise review_app.discord_notify.DiscordNotifyError("DISCORD_WEBHOOK_URL não está configurado no .env.")

    monkeypatch.setattr(review_app, "send_review_sort_list_to_discord", raise_error)

    r = client.post("/review/notify-discord")

    assert r.json() == {"sent": False, "error": "DISCORD_WEBHOOK_URL não está configurado no .env."}


def test_notify_discord_stock_endpoint_reports_success(monkeypatch, temp_db):
    monkeypatch.setattr(review_app, "send_stock_list_to_discord", lambda s: 7)

    r = client.post("/stock/notify-discord")

    assert r.json() == {"sent": True, "count": 7}


def test_notify_discord_stock_endpoint_reports_error(monkeypatch, temp_db):
    def raise_error(s):
        raise review_app.discord_notify.DiscordNotifyError("boom")

    monkeypatch.setattr(review_app, "send_stock_list_to_discord", raise_error)

    r = client.post("/stock/notify-discord")

    assert r.json() == {"sent": False, "error": "boom"}


def test_review_form_has_a_discord_button(temp_db):
    _add_book(temp_db, folder_path="book_discord_review", status="failed", isbn="1")

    r = client.get("/review")

    assert 'id="discord-review-btn"' in r.text
    assert "Enviar para Discord" in r.text


def test_stock_page_has_a_discord_button(temp_db):
    r = client.get("/stock")

    assert 'id="discord-stock-btn"' in r.text
    assert "Enviar para Discord" in r.text


# -------- Photos --------

def test_photo_rejects_unknown_filename(temp_db):
    book_id = _add_book(temp_db, folder_path="book_photo")

    r = client.get(f"/photo/{book_id}/secret.txt")

    assert r.status_code == 404


def test_photo_404s_when_file_missing_on_disk(temp_db):
    book_id = _add_book(temp_db, folder_path="book_no_photo_on_disk")

    r = client.get(f"/photo/{book_id}/cover.jpg")

    assert r.status_code == 404


def test_photo_serves_existing_file(temp_db, tmp_path):
    folder = tmp_path / "book_with_photo"
    folder.mkdir()
    (folder / "cover.jpg").write_bytes(b"fake-jpeg-bytes")
    book_id = _add_book(temp_db, folder_path=str(folder))

    r = client.get(f"/photo/{book_id}/cover.jpg")

    assert r.status_code == 200
    assert r.content == b"fake-jpeg-bytes"


def test_rotate_photo_turns_it_90_degrees_on_disk(temp_db, tmp_path):
    folder = tmp_path / "book_rotate"
    folder.mkdir()
    path = folder / "cover.jpg"
    Image.new("RGB", (100, 60), (10, 20, 30)).save(path, "JPEG")
    book_id = _add_book(temp_db, folder_path=str(folder))

    r = client.post(f"/photo/{book_id}/cover.jpg/rotate")

    assert r.json() == {"rotated": True}
    with Image.open(path) as rotated:
        assert rotated.size == (60, 100)  # width/height swapped - a real rotation, not a no-op


def test_rotate_photo_four_times_returns_to_original_orientation(temp_db, tmp_path):
    folder = tmp_path / "book_rotate_full_circle"
    folder.mkdir()
    path = folder / "cover.jpg"
    Image.new("RGB", (100, 60), (10, 20, 30)).save(path, "JPEG")
    book_id = _add_book(temp_db, folder_path=str(folder))

    for _ in range(4):
        client.post(f"/photo/{book_id}/cover.jpg/rotate")

    with Image.open(path) as final:
        assert final.size == (100, 60)


def test_rotate_photo_rejects_unknown_filename(temp_db):
    book_id = _add_book(temp_db, folder_path="book_rotate_bad_name")

    r = client.post(f"/photo/{book_id}/secret.txt/rotate")

    assert r.status_code == 404


def test_rotate_photo_404s_when_file_missing_on_disk(temp_db):
    book_id = _add_book(temp_db, folder_path="book_rotate_missing")

    r = client.post(f"/photo/{book_id}/cover.jpg/rotate")

    assert r.status_code == 404


def test_rotate_photo_404s_for_unknown_book(temp_db):
    r = client.post("/photo/999999/cover.jpg/rotate")
    assert r.status_code == 404


def test_review_form_has_rotate_buttons_for_both_photos(temp_db):
    book_id = _add_book(temp_db, folder_path="book_rotate_ui", title="Rotatable")

    r = client.get("/review")

    assert f"rotatePhoto({book_id}, 'cover.jpg', 'photo-cover-{book_id}')" in r.text
    assert f"rotatePhoto({book_id}, 'isbn.jpg', 'photo-isbn-{book_id}')" in r.text
