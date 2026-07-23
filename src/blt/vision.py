"""
Local, offline vision extraction via Ollama - no OpenAI, no cloud dependency.

Reads raw text off a book's cover/back photos. Deliberately does NOT try to
return clean structured fields here - that filtering step is separate
(keeps this module simple, and smaller local models tend to wrap JSON in
prose more than a hosted model would).
"""
import base64
from pathlib import Path

import requests

from .config import settings
from .images import resize_to_jpeg_bytes

_COVER_PROMPT = (
    "This is the front cover of a book. Transcribe all the text you can see on it "
    "as plainly as possible: title, author, publisher, any other visible text. "
    "Just the text, no commentary."
)
_BACK_PROMPT = (
    "This is the back cover of a book. Transcribe all the text you can see on it. "
    "Pay close attention to any ISBN number (often printed near a barcode, "
    "usually starting with 978 or 979). Just the text, no commentary."
)


class VisionError(RuntimeError):
    pass


def _encode_image(path: Path) -> str:
    return base64.b64encode(resize_to_jpeg_bytes(path)).decode("ascii")


def _generate(prompt: str, image_path: Path) -> str:
    try:
        r = requests.post(
            f"{settings.OLLAMA_HOST}/api/generate",
            json={
                "model": settings.OLLAMA_VISION_MODEL,
                "prompt": prompt,
                "images": [_encode_image(image_path)],
                "stream": False,
            },
            timeout=120,
        )
    except requests.RequestException as e:
        raise VisionError(
            f"Não foi possível contactar o Ollama em {settings.OLLAMA_HOST} ({e}). "
            "Confirma que o serviço está a correr."
        )
    if r.status_code >= 400:
        raise VisionError(f"Ollama devolveu erro {r.status_code}: {r.text[:300]}")
    try:
        return r.json()["response"]
    except (KeyError, ValueError) as e:
        raise VisionError(f"Resposta inesperada do Ollama: {e} - {r.text[:300]}")


def read_cover(path: Path) -> str:
    return _generate(_COVER_PROMPT, path)


def read_back(path: Path) -> str:
    return _generate(_BACK_PROMPT, path)


def extract_book_text(folder: Path) -> dict:
    """Reads cover.jpg and back.jpg in a book_NNN folder, returns raw text for each."""
    folder = Path(folder)
    return {
        "cover_text": read_cover(folder / "cover.jpg"),
        "back_text": read_back(folder / "back.jpg"),
    }
