"""
ISBN lookup against Almedina's own store search (almedina.net) - much better
coverage for Portuguese-market books (small local publishers, book-club
editions) than Google Books or Open Library, which frequently miss them.

Personal, low-volume use only (a handful of lookups a day, naturally spaced
out as books get photographed one at a time) - not for bulk scraping. Uses
an honest, self-identifying User-Agent rather than impersonating a browser.

Note: in testing, a burst of several requests within a couple of minutes
tripped a rate-limit/block even with a respectful pace - real usage (one
lookup every few minutes as you process each book) should stay well under
whatever that threshold is, but if it becomes a recurring problem, worth
asking their team to allowlist this kind of light personal use.
"""
import requests
from bs4 import BeautifulSoup

SEARCH_URL = "https://www.almedina.net/catalogsearch/result/"
HEADERS = {
    "User-Agent": "BookListingAutomation/1.0 (personal-use ISBN lookup; contact: gabryel321@gmail.com)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
}


class AlmedinaLookupError(RuntimeError):
    pass


def lookup_by_isbn(isbn: str) -> dict | None:
    """Returns {"title", "author"} or None if not found on Almedina."""
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
