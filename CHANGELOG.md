# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-07-27

First release: a working manual-assist tool for listing used books on Vinted.

### Added
- Photo intake: sort/pair raw phone photos chronologically into `book_NNN/cover.jpg + isbn.jpg`, with HEIC conversion.
- ISBN-first extraction: deterministic EAN-13 barcode decode (`pyzbar`) + a Portuguese bookstore (Almedina) site-search lookup, no vision-model guessing. Unresolved books are marked `failed` for manual entry rather than guessed.
- SQLite schema and book status state machine (`pending` → `available` → `sold_out`, with a `failed` side branch).
- PT description + flat-price composition, ready to paste into Vinted.
- Local FastAPI web app (`blt review`), organized as four steps behind a persistent sidebar and a live cross-page progress bar:
  - **Imagens raw** - review/confirm the proposed photo pairing before committing, with a per-pair cover/ISBN swap.
  - **Imagens ordenadas** - grouped books waiting on extraction.
  - **Livros por confirmar** - the copy-paste review/edit page.
  - **Stock** - searchable, sortable, paginated listing management: inline full-field editing, delete, and per-sale price capture.
  - Dashboard landing page with a live flow diagram, weekly bar charts, and running totals.
- Sales history: every unit sold is recorded as its own snapshot (title/isbn/price/timestamp), independent of the book row, so history survives even if the book is later deleted.
- `DEV_MODE` setting for safely re-running the whole pipeline against the same fixed test photos without consuming or losing data.
- CSRF mitigation (`Origin`/`Referer` check) on all state-changing routes, since the app has no auth by design.
- Project logo, used as the web app favicon/sidebar mark and the README banner.
- `uv`-based dependency management (`pyproject.toml` version constraints, `.python-version`, `uv.lock`), ruff + mypy with an 80% coverage gate, pre-commit hooks, and a rebuilt GitHub Actions CI pipeline.
- `LICENSE` (MIT), `SECURITY.md`, and `CLAUDE.md`.

### Fixed
- Almedina lookups were being blocked by an overly "honest" custom User-Agent string being filtered - switched to a real browser UA, which was the actual working configuration the whole time.
- A raw-photo `<img>` distortion bug in the progress-bar chart SVGs (`preserveAspectRatio="none"` on a variable-width viewBox).
- HEIC photos rendered as broken images in the browser (no native `<img>` support) - now converted to JPEG on the fly for display only.
- CI had been failing on every single run since the project's first commit: `pyzbar`'s Linux wheel doesn't bundle `libzbar` the way the Windows one does, so every test module importing the barcode decoder failed to collect. Fixed by installing `libzbar0` before the dependency install.
- Every `blt` command crashed after the `uv` migration bumped `click` to 8.4.x, which no longer accepted the `Optional[bool] = None` pattern used for `convert-heic`'s `--delete-src` flag ("Secondary flag is not valid for non-boolean flag"). Also fixed a related, previously-known `--help` rendering crash.

### Removed
- The earlier Vinted-posting-automation approach (Selenium, HTTP replay, Supabase storage) - abandoned after hitting real anti-bot systems (CAPTCHA, IP blocks, Datadome fingerprinting) on a real account. Kept as a historical reference on the `feat/vinted-http-api` branch; see the README for the full reasoning.
