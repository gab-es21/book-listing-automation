import re
import shutil
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from .config import settings
from .models import Base, Book

engine = create_engine(settings.DB_URL, future=True)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)

def init_db():
    Base.metadata.create_all(engine)

def sync_pending_books(grouped_dir: Path) -> int:
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
