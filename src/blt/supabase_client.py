from supabase import create_client, Client
from storage3 import SyncStorageClient
from .config import settings

_sb: Client | None = None
_storage: SyncStorageClient | None = None


def get_supabase() -> Client:
    global _sb
    if _sb is None:
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
            raise RuntimeError("Supabase URL/Service Role Key em falta no .env")
        _sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    return _sb


def get_storage() -> SyncStorageClient:
    """
    Create Storage client directly, compatible with multiple storage3 versions.
    Some versions accept (url, headers, timeout[, verify]); others just (url, headers[, timeout]).
    """
    global _storage
    if _storage is not None:
        return _storage

    url = f"{settings.SUPABASE_URL}/storage/v1"
    key = settings.SUPABASE_SERVICE_ROLE_KEY
    headers = {"apiKey": key, "Authorization": f"Bearer {key}"}

    # Try the broadest signature first; fall back gracefully.
    try:
        _storage = SyncStorageClient(url, headers, 20, True)   # url, headers, timeout, verify
    except TypeError:
        try:
            _storage = SyncStorageClient(url, headers, 20)      # url, headers, timeout
        except TypeError:
            _storage = SyncStorageClient(url, headers)          # url, headers

    return _storage
