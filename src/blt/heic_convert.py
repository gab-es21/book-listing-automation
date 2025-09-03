from __future__ import annotations
from pathlib import Path
from typing import Iterable
import subprocess, sys
from PIL import Image, UnidentifiedImageError

# Try to enable HEIC in Pillow (newer pillow-heif bundles libheif)
_HAVE_HEIF = False
try:
    from pillow_heif import register_heif_opener, open_heif  # type: ignore
    register_heif_opener()
    _HAVE_HEIF = True
except Exception:
    open_heif = None  # type: ignore

# Portable ffmpeg (auto-downloaded on first use, no system install)
_FFMPEG_EXE: str | None = None
def _get_ffmpeg_exe() -> str:
    global _FFMPEG_EXE
    if _FFMPEG_EXE:
        return _FFMPEG_EXE
    from imageio_ffmpeg import get_ffmpeg_exe  # lazy import
    _FFMPEG_EXE = get_ffmpeg_exe()
    return _FFMPEG_EXE

IMG_EXTS_HEIC = {".heic", ".heif"}

def _heic_to_jpeg_pillow(src: Path, dst: Path, quality: int = 95) -> bool:
    """Try Pillow + pillow-heif."""
    try:
        # First try normal PIL (register_heif_opener may be enough)
        im = Image.open(src)
    except UnidentifiedImageError:
        # Explicit open via pillow-heif as a fallback
        if _HAVE_HEIF and open_heif is not None and src.suffix.lower() in IMG_EXTS_HEIC:
            try:
                hf = open_heif(str(src), convert_hdr_to_8bit=True, apply_transformations=True, load_truncated=True)
                try:
                    im = hf.to_pillow()  # pillow-heif >= 0.17
                except AttributeError:
                    from PIL import Image as _PILImage
                    im = _PILImage.frombytes(hf.mode, hf.size, hf.data, "raw", hf.mode, hf.stride)
            except Exception:
                return False
        else:
            return False
    try:
        im = im.convert("RGB")
        im.save(dst, "JPEG", quality=quality, optimize=True)
        return True
    except Exception:
        return False

def _heic_to_jpeg_ffmpeg(src: Path, dst: Path, quality: int = 95) -> bool:
    """
    Use portable ffmpeg via imageio-ffmpeg.
    -q:v: lower is better quality; map quality∈[1..31]. We'll aim ~visually lossless: 2.
    """
    try:
        ffmpeg = _get_ffmpeg_exe()
        cmd = [ffmpeg, "-y", "-i", str(src), "-frames:v", "1", "-q:v", "2", str(dst)]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return proc.returncode == 0 and dst.exists()
    except Exception:
        return False

def convert_file(src: Path, delete_src: bool = True, quality: int = 95) -> Path | None:
    """
    Convert a single HEIC/HEIF file to JPEG (same stem).
    Returns destination path or None if it wasn't HEIC or conversion failed.
    """
    if src.suffix.lower() not in IMG_EXTS_HEIC:
        return None
    dst = src.with_suffix(".jpg")
    if _heic_to_jpeg_pillow(src, dst, quality=quality) or _heic_to_jpeg_ffmpeg(src, dst, quality=quality):
        if delete_src:
            try: src.unlink()
            except Exception: pass
        return dst
    return None

def convert_folder(folder: Path, recursive: bool = True, delete_src: bool = True, quality: int = 95) -> list[Path]:
    """
    Convert all HEIC/HEIF files under 'folder' to JPEG. Deletes originals if requested.
    Returns the list of created JPEG paths.
    """
    folder = Path(folder)
    pattern = "**/*" if recursive else "*"
    created: list[Path] = []
    for p in sorted(folder.glob(pattern)):
        if p.is_file() and p.suffix.lower() in IMG_EXTS_HEIC:
            out = convert_file(p, delete_src=delete_src, quality=quality)
            if out: created.append(out)
    return created
