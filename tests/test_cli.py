"""
CLI wiring tests: each command's argument parsing and glue with the already-
tested business logic (group_photos/db/extract/heic_convert). Not re-testing
that logic itself - just that `blt <command> [args]` invokes it correctly.

Also serves as a regression guard for the click/typer "Secondary flag is not
valid for non-boolean flag" incompatibility (a real bug hit once when the
click version was bumped): CliRunner.invoke builds the actual click Command,
so any recurrence of that error surfaces here as a crash on any invocation.
"""
from pathlib import Path

from typer.testing import CliRunner

from blt.cli import app

runner = CliRunner()


def test_initdb_calls_init_db(monkeypatch):
    calls = []
    monkeypatch.setattr("blt.cli.init_db", lambda: calls.append(True))

    result = runner.invoke(app, ["initdb"])

    assert result.exit_code == 0
    assert calls == [True]


def test_group_calls_group_last_set(monkeypatch):
    calls = []
    monkeypatch.setattr("blt.cli.group_last_set", lambda: calls.append(True))

    result = runner.invoke(app, ["group"])

    assert result.exit_code == 0
    assert calls == [True]


def test_group_all_passes_max_groups_and_syncs_pending(monkeypatch):
    import blt.db as db
    import blt.group_photos as group_photos

    calls = {}
    monkeypatch.setattr(group_photos, "group_all", lambda max_groups=None: calls.update(max_groups=max_groups))
    monkeypatch.setattr(db, "sync_pending_books", lambda grouped_dir: 3)

    result = runner.invoke(app, ["group-all", "--max-groups", "5"])

    assert result.exit_code == 0
    assert calls == {"max_groups": 5}
    assert "3 livro" in result.output


def test_group_all_resets_pending_books_in_dev_mode(monkeypatch):
    import blt.db as db
    import blt.group_photos as group_photos
    from blt.config import settings

    monkeypatch.setattr(settings, "DEV_MODE", True)
    monkeypatch.setattr(group_photos, "group_all", lambda max_groups=None: None)
    monkeypatch.setattr(db, "sync_pending_books", lambda grouped_dir: 0)
    reset_calls = []
    monkeypatch.setattr(db, "reset_dev_pending_books", lambda: reset_calls.append(True) or 2)

    result = runner.invoke(app, ["group-all"])

    assert result.exit_code == 0
    assert reset_calls == [True]
    assert "reiniciados" in result.output


def test_extract_passes_limit(monkeypatch):
    import blt.extract as extract

    captured = {}

    def fake_extract(limit=None):
        captured["limit"] = limit
        return {"resolved": 1, "failed": 0}

    monkeypatch.setattr(extract, "extract_pending_books", fake_extract)

    result = runner.invoke(app, ["extract", "--limit", "10"])

    assert result.exit_code == 0
    assert captured == {"limit": 10}
    assert "1 resolvido" in result.output


def test_review_starts_uvicorn_with_host_and_port(monkeypatch):
    import uvicorn

    captured = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, host, port: captured.update(host=host, port=port))

    result = runner.invoke(app, ["review", "--host", "0.0.0.0", "--port", "9000"])

    assert result.exit_code == 0
    assert captured == {"host": "0.0.0.0", "port": 9000}


def test_convert_heic_passes_path_and_flags(monkeypatch):
    import blt.heic_convert as heic_convert

    captured = {}

    def fake_convert_folder(folder, recursive=True, delete_src=True):
        captured.update(folder=folder, recursive=recursive, delete_src=delete_src)
        return ["a.jpg", "b.jpg"]

    monkeypatch.setattr(heic_convert, "convert_folder", fake_convert_folder)

    result = runner.invoke(app, ["convert-heic", "some/dir", "--no-recursive", "--delete-src"])

    assert result.exit_code == 0
    assert captured == {"folder": Path("some/dir"), "recursive": False, "delete_src": True}
    assert "2 ficheiro" in result.output
