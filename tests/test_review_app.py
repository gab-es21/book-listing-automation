import os
import time

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from blt import review_app
from blt.models import Book, Sale
from blt.review_app import app

client = TestClient(app)


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
    assert 'title="Imagens raw: 33.3%"' in r.text
    assert 'title="Por confirmar: 66.7%"' in r.text


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
    assert 'title="Imagens raw: 50.0%"' in r.text
    assert 'title="Por confirmar: 50.0%"' in r.text


def test_progress_header_handles_zero_books_without_crashing(monkeypatch, tmp_path, temp_db):
    raw = tmp_path / "raw"
    raw.mkdir()
    monkeypatch.setattr(review_app.settings, "RAW_DIR", str(raw))

    r = client.get("/review")

    assert r.status_code == 200
    assert 'title="Imagens raw: 0.0%"' in r.text
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


def test_next_advances_to_the_next_pending_book(temp_db):
    _add_book(temp_db, folder_path="book_a", title="First")
    _add_book(temp_db, folder_path="book_b", title="Second")

    with temp_db() as s:
        first_id = s.execute(select(Book).where(Book.folder_path == "book_a")).scalar_one().id

    client.post("/next", data={"book_id": first_id, "price": "7.0", "quantity": "1"})

    r = client.get("/review")
    assert "Second" in r.text
    assert "First" not in r.text


def test_dev_mode_next_does_not_promote_saves_edits_and_stays_pending(monkeypatch, temp_db):
    monkeypatch.setattr(review_app.settings, "DEV_MODE", True)
    book_id = _add_book(temp_db, folder_path="book_dev", title="Old")

    client.post("/next", data={"book_id": book_id, "title": "Edited", "price": "7.0", "quantity": "1"})

    with temp_db() as s:
        book = s.get(Book, book_id)
        assert book.title == "Edited"  # edits are still saved
        assert book.status == "pending"  # but never promoted


def test_dev_mode_next_cycles_to_the_next_book_via_after_cursor(monkeypatch, temp_db):
    monkeypatch.setattr(review_app.settings, "DEV_MODE", True)
    first_id = _add_book(temp_db, folder_path="book_a", title="First")
    _add_book(temp_db, folder_path="book_b", title="Second")

    r = client.post("/next", data={"book_id": first_id, "price": "7.0", "quantity": "1"}, follow_redirects=True)

    assert "Second" in r.text
    with temp_db() as s:
        assert s.get(Book, first_id).status == "pending"  # book_a never left the queue


def test_dev_mode_wraps_around_after_the_last_book(monkeypatch, temp_db):
    monkeypatch.setattr(review_app.settings, "DEV_MODE", True)
    _add_book(temp_db, folder_path="book_a", title="First")
    last_id = _add_book(temp_db, folder_path="book_b", title="Second")

    r = client.get("/review", params={"after": last_id})

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


# -------- Stock --------

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
