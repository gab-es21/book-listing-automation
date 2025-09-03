__version__ = "0.1.0"

# Enable HEIC/HEIF decoding for Pillow as early as possible
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    # Keep going even if plugin isn't available
    pass
