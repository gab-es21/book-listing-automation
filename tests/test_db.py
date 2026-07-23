from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from blt import db
from blt.models import Base, Book


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", session_factory)
    return session_factory


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
