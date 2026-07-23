import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from blt import db
from blt.models import Base


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """A fresh, isolated SQLite DB per test - swaps blt.db's engine/SessionLocal."""
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", session_factory)
    return session_factory
