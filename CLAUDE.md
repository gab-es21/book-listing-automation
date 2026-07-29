# CLAUDE.md

Context for any LLM/agent session (Claude Code or otherwise) working on this repo.

## Tech stack

- Python >=3.10 (developed against 3.12, pinned in `.python-version`).
- Dependency/venv management: **uv** — never call `pip`/`venv` directly.
- FastAPI + Jinja2 + SQLAlchemy 2.x + SQLite for the local review app; Typer for the `blt` CLI.
- ruff (lint) + mypy (types) + pytest/pytest-cov (tests, 80% coverage gate) + pre-commit.

## Commands

| Task | Command |
|---|---|
| Install everything | `uv sync` |
| Run any CLI command | `uv run blt <command>` (see README for the list) |
| Start the review app | `uv run blt review` |
| Lint | `uv run ruff check .` (`--fix` to auto-fix) |
| Type check | `uv run mypy src` |
| Tests | `uv run pytest -v` |
| Tests + coverage | `uv run pytest --cov=blt --cov-report=term-missing` |
| Pre-commit, ad hoc | `uv run pre-commit run --all-files` |
| Add a dependency | `uv add <pkg>` / `uv add --dev <pkg>` |

CI (`.github/workflows/ci.yml`) runs `uv sync --locked`, ruff, mypy, and pytest-with-coverage on every push/PR — all four must pass.

## Workflow rules

- Never push directly to `main` or `alpha`. Work happens on `feature/*`/`fix/*` branches cut from `alpha`, merged via PR.
- Keep diffs small and surgical — one focused change per branch.
- **Plan before code**: for anything non-trivial, present a short plan (what changes, which files, what tests) and get sign-off before implementing.
- A feature isn't done until its tests, its CHANGELOG entry, and any doc updates land in the *same* PR — never "docs later."
- Ask before anything destructive or hard to reverse: deleting branches with unmerged work, force-pushing, rewriting git history, deleting real data (`blt.db`, photo folders).
- Don't add code-style opinions here — ruff/mypy already enforce those deterministically.

## Things to know before changing behavior

- This is a **manual-assist** tool, not Vinted automation — deliberately, after the automated approach hit anti-bot systems on a real account (see README). Don't reintroduce direct posting/API automation without discussing it first.
- Almedina lookups are personal, low-volume, and rate-limited by design (a small random delay in `almedina_lookup.py`). Don't remove the delay or scale up request volume — this only works because it stays under the radar of a site that hasn't explicitly authorized bulk use.
- `isbnsearch_lookup.py` is a second-source fallback tried only when Almedina misses — it was added after checking its `robots.txt` allows every crawler (several other candidates were rejected for disallowing the needed path, or naming AI/Claude bots explicitly). Same small random delay as Almedina applies. Before adding another external lookup source, check its `robots.txt` first — that's the deciding factor, not just "does it have the data."
- `DEV_MODE` (`.env`) changes pipeline behavior for repeatable local testing (see README's "Development mode" section for the exact guarantees). It must never let a real `available`/`sold_out` book or a real sale be lost or altered.
- The review app has no authentication by design (single-user, localhost-only). The Origin/Referer CSRF check in `review_app.py` is the only thing standing between that and a real cross-origin write — don't remove it without replacing it with something at least as strong.
- Discord notifications (`discord_notify.py`) are a plain webhook (`DISCORD_WEBHOOK_URL` in `.env`, optional), not a bot — no token, no persistent process. Keep it that way; don't introduce `discord.py` or a bot process for this without discussing it first, since nothing here needs two-way control from Discord.
