from pathlib import Path

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from blt import db
from blt.models import Book, BookPlatform, Sale


def _make_book_folders(base: Path, names):
    for n in names:
        (base / n).mkdir(parents=True)


def test_sync_creates_pending_rows_for_new_folders(tmp_path, temp_db):
    grouped = tmp_path / "grouped"
    _make_book_folders(grouped, ["book_001", "book_002"])

    added = db.sync_pending_books(grouped)

    assert added == 2
    with temp_db() as s:
        books = s.execute(select(Book).order_by(Book.folder_path)).scalars().all()
        assert [b.status for b in books] == ["pending", "pending"]
        assert {b.folder_path for b in books} == {
            str(grouped / "book_001"),
            str(grouped / "book_002"),
        }


def test_sync_is_idempotent(tmp_path, temp_db):
    grouped = tmp_path / "grouped"
    _make_book_folders(grouped, ["book_001"])

    first = db.sync_pending_books(grouped)
    second = db.sync_pending_books(grouped)

    assert first == 1
    assert second == 0
    with temp_db() as s:
        assert len(s.execute(select(Book)).scalars().all()) == 1


def test_sync_ignores_non_book_folders(tmp_path, temp_db):
    grouped = tmp_path / "grouped"
    _make_book_folders(grouped, ["book_001", "not_a_book", "random"])

    added = db.sync_pending_books(grouped)

    assert added == 1


def test_sync_missing_dir_returns_zero(tmp_path, temp_db):
    added = db.sync_pending_books(tmp_path / "does_not_exist")
    assert added == 0


def test_reset_dev_pending_books_removes_pending_and_failed_only(tmp_path, temp_db):
    pending_folder = tmp_path / "book_001"
    failed_folder = tmp_path / "book_002"
    available_folder = tmp_path / "book_003"
    sold_out_folder = tmp_path / "book_004"
    for f in (pending_folder, failed_folder, available_folder, sold_out_folder):
        f.mkdir()

    with temp_db() as s:
        s.add(Book(folder_path=str(pending_folder), status="pending"))
        s.add(Book(folder_path=str(failed_folder), status="failed"))
        s.add(Book(folder_path=str(available_folder), status="available", title="Real Listing"))
        s.add(Book(folder_path=str(sold_out_folder), status="sold_out", title="Sold Already"))
        s.commit()

    removed = db.reset_dev_pending_books()

    assert removed == 2
    assert not pending_folder.exists()
    assert not failed_folder.exists()
    assert available_folder.exists()  # real inventory - never touched
    assert sold_out_folder.exists()

    with temp_db() as s:
        remaining = s.execute(select(Book)).scalars().all()
        assert {b.status for b in remaining} == {"available", "sold_out"}


def test_reset_dev_pending_books_is_a_noop_when_nothing_to_clear(temp_db):
    with temp_db() as s:
        s.add(Book(folder_path="x", status="available", title="Real Listing"))
        s.commit()

    assert db.reset_dev_pending_books() == 0


def test_portuguese_characters_survive_a_real_roundtrip(temp_db):
    """Guards against mojibake: title/description with ç/ã/õ/é must come back byte-identical."""
    title = "Uma Obsessão Indecente"
    description = "Edição em bom estado. Entrega em mão na Covilhã, senão Correio."

    with temp_db() as s:
        s.add(Book(folder_path="x", title=title, description=description))
        s.commit()

    # fresh session forces an actual read back through SQLite, not just the cached object
    with temp_db() as s:
        b = s.execute(select(Book)).scalar_one()
        assert b.title == title
        assert b.description == description


def test_init_db_adds_missing_sale_platform_column_to_an_existing_database(tmp_path, monkeypatch):
    """
    Base.metadata.create_all only creates missing tables, not missing columns
    on tables that already exist - so a real blt.db predating Sale.platform
    must get it added in place by init_db(), without losing any existing
    row's data.
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'old_schema.db'}", future=True)
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE books (id INTEGER PRIMARY KEY, title VARCHAR(255), author VARCHAR(255), "
            "isbn VARCHAR(32), description TEXT, price FLOAT, quantity INTEGER, status VARCHAR(32), "
            "folder_path VARCHAR(512) UNIQUE, created_at DATETIME, updated_at DATETIME, skipped_at DATETIME)"
        ))
        conn.execute(text(
            "INSERT INTO books (title, folder_path, status, quantity, price) "
            "VALUES ('Old Book', 'book_x', 'available', 3, 7.5)"
        ))
        conn.execute(text(
            "CREATE TABLE sales (id INTEGER PRIMARY KEY, book_id INTEGER, title VARCHAR(255), "
            "isbn VARCHAR(32), price FLOAT, sold_at DATETIME)"
        ))
        conn.execute(text("INSERT INTO sales (book_id, title, isbn, price) VALUES (1, 'Old Sale', '123', 7.5)"))

    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False, future=True))

    db.init_db()

    with engine.connect() as conn:
        sale_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(sales)"))}
    assert "platform" in sale_cols

    with db.SessionLocal() as s:
        book = s.execute(select(Book)).scalar_one()
        assert book.title == "Old Book"  # untouched by the migration
        assert book.quantity == 3
        assert book.platforms == []  # book_platforms table is new, nothing to backfill here

        sale = s.execute(select(Sale)).scalar_one()
        assert sale.title == "Old Sale"  # untouched
        assert sale.platform is None


def test_init_db_migrates_boolean_platform_columns_to_book_platforms(tmp_path, monkeypatch):
    """
    books briefly had on_vinted/on_olx/on_marketplace boolean columns before
    the book_platforms join table replaced them (to support a config-driven,
    growable list of marketplaces instead of one column per platform).
    init_db() must upgrade a database still on that intermediate shape:
    backfill book_platforms from the booleans, then drop them - without
    losing any book's other data.
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'boolean_schema.db'}", future=True)
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE books (id INTEGER PRIMARY KEY, title VARCHAR(255), author VARCHAR(255), "
            "isbn VARCHAR(32), description TEXT, price FLOAT, quantity INTEGER, status VARCHAR(32), "
            "folder_path VARCHAR(512) UNIQUE, created_at DATETIME, updated_at DATETIME, skipped_at DATETIME, "
            "on_vinted BOOLEAN DEFAULT 1, on_olx BOOLEAN DEFAULT 0, on_marketplace BOOLEAN DEFAULT 0)"
        ))
        conn.execute(text(
            "INSERT INTO books (title, folder_path, status, quantity, price, on_vinted, on_olx, on_marketplace) "
            "VALUES ('Cross Posted', 'book_a', 'available', 2, 7.5, 1, 1, 0)"
        ))
        conn.execute(text(
            "INSERT INTO books (title, folder_path, status, quantity, price, on_vinted, on_olx, on_marketplace) "
            "VALUES ('Vinted Only', 'book_b', 'available', 1, 6.0, 1, 0, 0)"
        ))
        conn.execute(text(
            "INSERT INTO books (title, folder_path, status, quantity, price, on_vinted, on_olx, on_marketplace) "
            "VALUES ('Nowhere Yet', 'book_c', 'pending', 1, 5.0, 0, 0, 0)"
        ))
        conn.execute(text(
            "CREATE TABLE sales (id INTEGER PRIMARY KEY, book_id INTEGER, title VARCHAR(255), "
            "isbn VARCHAR(32), price FLOAT, sold_at DATETIME)"
        ))

    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False, future=True))

    db.init_db()

    with engine.connect() as conn:
        book_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(books)"))}
    assert not {"on_vinted", "on_olx", "on_marketplace"} & book_cols  # dropped

    with db.SessionLocal() as s:
        cross_posted = s.execute(select(Book).where(Book.title == "Cross Posted")).scalar_one()
        vinted_only = s.execute(select(Book).where(Book.title == "Vinted Only")).scalar_one()
        nowhere_yet = s.execute(select(Book).where(Book.title == "Nowhere Yet")).scalar_one()

        assert cross_posted.quantity == 2  # untouched by the migration
        assert {bp.platform for bp in cross_posted.platforms} == {"vinted", "olx"}
        assert {bp.platform for bp in vinted_only.platforms} == {"vinted"}
        assert nowhere_yet.platforms == []


def test_init_db_boolean_migration_is_a_noop_on_a_fresh_database(tmp_path, monkeypatch):
    """A brand new database never had the boolean columns at all - nothing
    to backfill, must not error."""
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}", future=True)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False, future=True))

    db.init_db()

    with db.SessionLocal() as s:
        s.add(Book(folder_path="x", platforms=[BookPlatform(platform="vinted")]))
        s.commit()
        book = s.execute(select(Book)).scalar_one()
        assert [bp.platform for bp in book.platforms] == ["vinted"]


def test_init_db_is_idempotent_on_an_already_upgraded_database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}", future=True)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False, future=True))

    db.init_db()
    db.init_db()  # must not error or duplicate columns/tables on a second call

    with engine.connect() as conn:
        sale_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(sales)"))]
    assert sale_cols.count("platform") == 1
