from fastapi.testclient import TestClient
from sqlalchemy import select

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


def test_review_form_shows_nothing_left_when_no_books(temp_db):
    r = client.get("/")
    assert r.status_code == 200
    assert "Não há livros por rever" in r.text


def test_review_form_shows_oldest_pending_book(temp_db):
    _add_book(temp_db, folder_path="book_001", title="Sempre Tu", isbn="9789896689704")

    r = client.get("/")

    assert r.status_code == 200
    assert "Sempre Tu" in r.text
    assert "9789896689704" in r.text
    assert "1 livro" in r.text


def test_failed_book_shows_blank_title_but_keeps_isbn(temp_db):
    _add_book(temp_db, folder_path="book_002", status="failed", title=None, isbn="9789896689704")

    r = client.get("/")

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

    assert r.status_code == 200  # followed the redirect to /
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

    r = client.get("/")
    assert "Second" in r.text
    assert "First" not in r.text


def test_available_list_shows_available_books(temp_db):
    _add_book(temp_db, folder_path="book_avail", title="Available Book", status="available", quantity=3)

    r = client.get("/available")

    assert r.status_code == 200
    assert "Available Book" in r.text
    assert ">3<" in r.text


def test_mark_sold_decrements_quantity(temp_db):
    book_id = _add_book(temp_db, folder_path="book_stock", status="available", quantity=2)

    client.post(f"/sold/{book_id}")

    with temp_db() as s:
        book = s.get(Book, book_id)
        assert book.quantity == 1
        assert book.status == "available"


def test_mark_sold_flips_to_sold_out_at_zero(temp_db):
    book_id = _add_book(temp_db, folder_path="book_last", status="available", quantity=1)

    client.post(f"/sold/{book_id}")

    with temp_db() as s:
        book = s.get(Book, book_id)
        assert book.quantity == 0
        assert book.status == "sold_out"

    r = client.get("/available")
    assert "book_last" not in r.text


def test_sold_out_book_does_not_appear_in_available_list(temp_db):
    book_id = _add_book(temp_db, folder_path="book_gone", status="sold_out", quantity=0, title="Gone")

    r = client.get("/available")

    assert "Gone" not in r.text


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

    r = client.get("/")
    assert "Oops" in r.text


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
