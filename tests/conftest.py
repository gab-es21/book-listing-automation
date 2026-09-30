import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from blt import db, review_app
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


@pytest.fixture(autouse=True)
def _reset_bundle_tmp_dir_state():
    """_pending_bundle_tmp_dir is process-global (single-user app, no request
    to scope it to) - reset around every test so one test's /bundle calls
    can't leak state into an unrelated one."""
    review_app._pending_bundle_tmp_dir = None
    yield
    review_app._pending_bundle_tmp_dir = None
