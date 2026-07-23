"""
Given a validated ISBN, look up the canonical title/author from a free
public book database (Google Books) - far more reliable than guessing
title/author off a photographed cover with a local vision model.
"""
import requests

from .config import settings

GOOGLE_BOOKS_API = "https://www.googleapis.com/books/v1/volumes"


class BookLookupError(RuntimeError):
    pass


def lookup_by_isbn(isbn: str) -> dict | None:
    """Returns {"title", "author"} or None if the ISBN isn't in Google Books."""
    params = {"q": f"isbn:{isbn}"}
    if settings.GOOGLE_BOOKS_API_KEY:
        params["key"] = settings.GOOGLE_BOOKS_API_KEY
    try:
        r = requests.get(GOOGLE_BOOKS_API, params=params, timeout=10)
        r.raise_for_status()
    except requests.RequestException as e:
        raise BookLookupError(f"Não foi possível consultar a Google Books API ({e}).")

    items = r.json().get("items") or []
    if not items:
        return None
    info = items[0].get("volumeInfo", {})
    authors = info.get("authors") or []
    return {
        "title": info.get("title"),
        "author": ", ".join(authors) if authors else None,
    }
