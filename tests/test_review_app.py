import os
import time

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from blt import review_app
from blt.models import Book
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
    assert all(abs(a - e) <= tol for a, e in zip(actual, expected)), f"{actual} != {expected} (tol={tol})"


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

    assert '<a class="sidebar-title" href="/">BookListing</a>' in r.text


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
    first_id = _add_book(temp_db, folder_path="book_a", title="First")
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
