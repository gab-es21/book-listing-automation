from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class Settings(BaseSettings):
    PHOTOS_PER_BOOK: int = 2
    RAW_DIR: str = "photos_raw"
    GROUPED_DIR: str = "photos_grouped"
    DB_URL: str = "sqlite:///./blt.db"
    TZ: str = "Europe/Lisbon"

    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str | None = None  # ex: gpt-4o-mini

    VINTED_EMAIL: str | None = None
    VINTED_PASSWORD: str | None = None
    VINTED_LOCATION: str | None = None
    VINTED_SHIPPING: str | None = None

    PRICE_MIN: float = 5.0
    PRICE_MARGIN_EUR: float = 2.0

    SUPABASE_URL: str | None = None
    SUPABASE_SERVICE_ROLE_KEY: str | None = None
    SUPABASE_BUCKET: str = "books"

    # Vision (upload temporário)
    VISION_MAX_IMAGES: int = 2
    VISION_UPLOAD_PREFIX: str = "vision"
    VISION_SIGNED_URL_TTL: int = 300
    VISION_MAX_SIDE: int = 1280
    VISION_JPEG_QUALITY: int = 85

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
os.makedirs(settings.RAW_DIR, exist_ok=True)
os.makedirs(settings.GROUPED_DIR, exist_ok=True)
