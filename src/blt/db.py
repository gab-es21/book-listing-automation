import re
import shutil
from pathlib import Path

from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.orm import sessionmaker

from .config import settings
from .models import Base, Book

engine = create_engine(settings.DB_URL, future=True)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)

# Base.metadata.create_all only creates missing *tables*, not missing
# *columns* on tables that already exist - so upgrading an existing blt.db
# (real inventory data) to a schema with new columns needs an explicit,
# additive ALTER TABLE step. Existing rows keep all their other data; the
# new column is simply backfilled with its default for them.
_SALE_COLUMNS_TO_ADD = [
    ("platform", "VARCHAR(32)"),
]

# books briefly had these instead of the book_platforms join table.
_BOOLEAN_PLATFORM_COLUMNS = (("vinted", "on_vinted"), ("olx", "on_olx"), ("marketplace", "on_marketplace"))


def _ensure_columns(engine: Engine, table: str, columns: list[tuple[str, str]]) -> None:
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
        for name, ddl in columns:
            if name not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def _migrate_book_platforms_from_booleans(engine: Engine) -> None:
    """
    books briefly had on_vinted/on_olx/on_marketplace boolean columns,
    superseded by the book_platforms join table so the set of marketplaces
    can grow via platforms.json without a schema change. Upgrades a database
    still on that intermediate shape: backfills book_platforms from the
    booleans, then drops them. A no-op on a fresh database (nothing to
    backfill) or one already upgraded (columns already gone) - requires
    book_platforms to already exist, so must run after create_all.
    """
    with engine.begin() as conn:
        book_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(books)"))}
        if "on_vinted" not in book_cols:
            return
        for slug, column in _BOOLEAN_PLATFORM_COLUMNS:
            conn.execute(
                text(f"INSERT INTO book_platforms (book_id, platform) SELECT id, :slug FROM books WHERE {column} = 1"),
                {"slug": slug},
            )
        for _, column in _BOOLEAN_PLATFORM_COLUMNS:
            conn.execute(text(f"ALTER TABLE books DROP COLUMN {column}"))


def init_db():
    Base.metadata.create_all(engine)
    _ensure_columns(engine, "sales", _SALE_COLUMNS_TO_ADD)
    _migrate_book_platforms_from_booleans(engine)

def sync_pending_books(grouped_dir: str | Path) -> int:
    """
    Ensure every book_NNN folder in grouped_dir has a matching Book row,
    inserting one with status="pending" for any that don't yet have one.
    Safe to call repeatedly - already-registered folders are skipped.
    """
    grouped_dir = Path(grouped_dir)
    if not grouped_dir.exists():
        return 0

    with SessionLocal() as s:
        existing = {row[0] for row in s.execute(select(Book.folder_path)).all()}
        added = 0
        for folder in sorted(grouped_dir.iterdir()):
            if not folder.is_dir() or not re.match(r"book_\d{3,}$", folder.name):
                continue
            if str(folder) in existing:
                continue
            s.add(Book(folder_path=str(folder), status="pending"))
            added += 1
        s.commit()
        return added

def reset_dev_pending_books() -> int:
    """
    DEV_MODE only: deletes every Book row still status in (pending, failed)
    along with its book_NNN folder, so a dev-mode group-all always starts
    from the same clean slate instead of piling up more books every run.
    Never touches available/sold_out rows - those are real listing/sale
    history, not dev fixtures, and must survive regardless of DEV_MODE.
    """
    with SessionLocal() as s:
        rows = s.execute(select(Book).where(Book.status.in_(("pending", "failed")))).scalars().all()
        removed = 0
        for book in rows:
            folder = Path(book.folder_path)
            if folder.exists():
                shutil.rmtree(folder)
            s.delete(book)
            removed += 1
        s.commit()
        return removed
