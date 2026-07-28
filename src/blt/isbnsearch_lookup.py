"""
ISBN lookup against isbnsearch.org - a second attempt for when Almedina
doesn't have the book (a common gap for foreign/mass-market imprints
Almedina's own small-publisher-focused catalog doesn't carry).

Checked deliberately before adding this: isbnsearch.org's robots.txt is
wide open (`Allow: /` for every crawler, no Disallow at all), unlike
several other candidates that were considered and rejected specifically
because their robots.txt disallowed exactly this kind of access (or, in
one case, named AI/Claude bots explicitly). It's a small ad/affiliate-
supported reference site (Amazon Associate links, "sell this book"
referrals) - scraping its metadata doesn't undercut a business built on
selling that data, unlike a dedicated ISBN-database vendor.

An honest, self-identifying User-Agent works fine here (confirmed
directly) - no need for the browser-UA workaround Almedina requires.

A small random delay is still applied before every request, same as
Almedina, as simple good manners regardless of what's technically
required.
"""
import random
import time

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://isbnsearch.org/isbn/"
HEADERS = {
    "User-Agent": "BookListingAutomation/1.0 (personal-use ISBN lookup)",
}


class IsbnSearchLookupError(RuntimeError):
    pass


def lookup_by_isbn(isbn: str) -> dict | None:
    """Returns {"title", "author"} or None if not found on isbnsearch.org."""
    time.sleep(random.uniform(0.5, 1.5))
    try:
        r = requests.get(BASE_URL + isbn, headers=HEADERS, timeout=15)
        if r.status_code == 404:
            return None
        r.raise_for_status()
    except requests.RequestException as e:
        raise IsbnSearchLookupError(f"Não foi possível consultar isbnsearch.org ({e}).") from e

    soup = BeautifulSoup(r.text, "html.parser")
    bookinfo = soup.find("div", class_="bookinfo")
    if not bookinfo:
        return None

    title_el = bookinfo.find("h1")
    title = title_el.get_text(strip=True) if title_el else None
    if not title:
        return None

    author = None
    for p in bookinfo.find_all("p"):
        strong = p.find("strong")
        if strong and strong.get_text(strip=True) == "Author:" and strong.next_sibling:
            author = str(strong.next_sibling).strip() or None
            break

    return {"title": title, "author": author}
