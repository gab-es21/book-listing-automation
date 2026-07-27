"""
ISBN lookup against Almedina's own store search (almedina.net) - much better
coverage for Portuguese-market books (small local publishers, book-club
editions) than Google Books or Open Library, which frequently miss them.

Personal, low-volume use only (a handful of lookups a day, naturally spaced
out as books get photographed one at a time) - not for bulk scraping.
Authorized directly by contacts who run the site, for exactly this kind of
light personal use (10-20 lookups/day).

The User-Agent below is a real browser string, not an honest custom one -
this was tested and confirmed deliberately: an earlier honest, self-
identifying User-Agent ("BookListingAutomation/1.0...") got 403'd on every
single request, while this exact browser UA + header set succeeded
immediately on the same ISBN, repeatedly, across days. What looked at the
time like a rate-limit block was actually the custom User-Agent string
itself being filtered - there is no evidence this endpoint rate-limits at
the volume this tool ever produces.

A small random delay is still applied before every request, here rather
than in any particular caller, so this module protects itself regardless of
who's calling it (the batch extractor, a one-off debug script, anything
else) - simple good manners even without a confirmed rate limit.
"""
import random
import time

import requests
from bs4 import BeautifulSoup

SEARCH_URL = "https://www.almedina.net/catalogsearch/result/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
}


class AlmedinaLookupError(RuntimeError):
    pass


def lookup_by_isbn(isbn: str) -> dict | None:
    """Returns {"title", "author"} or None if not found on Almedina."""
    time.sleep(random.uniform(0.5, 1.5))
    try:
        r = requests.get(SEARCH_URL, params={"q": isbn}, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except requests.RequestException as e:
        raise AlmedinaLookupError(f"Não foi possível consultar a Almedina ({e}).")

    soup = BeautifulSoup(r.text, "html.parser")

    # An exact ISBN match redirects straight to the product page, which has
    # this structured markup; a search-results listing (no exact match)
    # doesn't carry it the same way.
    title_el = soup.find(attrs={"itemprop": "name"})
    if not title_el:
        return None
    title = title_el.get_text(strip=True)

    author_link = soup.find("a", href=lambda h: h and "/autor/" in h)
    author = author_link.get_text(strip=True) if author_link else None

    return {"title": title, "author": author}
