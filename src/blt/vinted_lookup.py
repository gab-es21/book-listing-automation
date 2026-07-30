"""
ISBN lookup against Vinted's internal item upload API (vinted.pt).

Useful for retrieving autofilled book metadata directly from Vinted's own
catalog database when creating listings.

Personal, low-volume use only. To avoid triggering Cloudflare Bot Management
(Cf-Mitigated challenges), requests are executed using curl_cffi to impersonate
a real Chrome browser TLS fingerprint alongside an unauthenticated guest session.

A small random delay is applied before every request to keep access light
and polite.
"""
import random
import time

from curl_cffi import requests

API_URL = "https://www.vinted.pt/api/v2/item_upload/isbn_records"
HOME_URL = "https://www.vinted.pt/"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.vinted.pt/items/new",
    "X-Requested-With": "XMLHttpRequest",
}


class VintedLookupError(RuntimeError):
    pass


# Global session cache so repeated lookups reuse Cloudflare clearance cookies
_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session(impersonate="chrome120")
        try:
            # Seed session with Cloudflare clearance cookies from homepage
            _session.get(HOME_URL, timeout=15)
        except Exception as e:
            _session = None
            raise VintedLookupError(f"Não foi possível inicializar a sessão do Vinted ({e}).") from e
    return _session


def lookup_by_isbn(isbn: str) -> dict | None:
    """Returns {"title", "author"} or None if not found on Vinted."""
    time.sleep(random.uniform(0.5, 1.5))
    session = _get_session()

    try:
        r = session.get(API_URL, params={"isbn": isbn}, headers=HEADERS, timeout=15)

        if r.status_code == 404:
            return None
        elif r.status_code in (403, 429):
            # Reset cached session if blocked or rate-limited
            global _session
            _session = None
            raise VintedLookupError(f"Acesso bloqueado pelo Vinted/Cloudflare (status {r.status_code}).")

        r.raise_for_status()
        data = r.json()
    except requests.RequestsError as e:
        raise VintedLookupError(f"Não foi possível consultar o Vinted ({e}).") from e

    # Extract metadata using Vinted's internal structure
    records = data.get("isbn_records") or {}
    title = records.get("book_title")
    author = records.get("author")

    if not title and not author:
        return None

    return {"title": title, "author": author}
