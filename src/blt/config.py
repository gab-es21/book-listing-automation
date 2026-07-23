from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class Settings(BaseSettings):
    PHOTOS_PER_BOOK: int = 2
    RAW_DIR: str = "photos_raw"
    GROUPED_DIR: str = "photos_grouped"
    DB_URL: str = "sqlite:///./blt.db"
    TZ: str = "Europe/Lisbon"

    # Local vision extraction (Ollama - no cloud dependency)
    OLLAMA_HOST: str = "http://localhost:11434"
    OLLAMA_VISION_MODEL: str = "gemma3:4b"
    OLLAMA_FILTER_MODEL: str = "llama3.2:3b"

    # Info fixa usada para compor a descrição (categoria/condição/idioma são
    # sempre os mesmos e escolhidos à mão no Vinted, por isso não são geridos aqui)
    SELLER_LOCATION: str | None = None
    SELLER_SHIPPING: str | None = None

    PRICE_MIN: float = 5.0
    PRICE_MARGIN_EUR: float = 2.0

    # Redimensionamento de imagens antes de enviar ao modelo de visão local
    VISION_MAX_SIDE: int = 1280
    VISION_JPEG_QUALITY: int = 85

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
os.makedirs(settings.RAW_DIR, exist_ok=True)
os.makedirs(settings.GROUPED_DIR, exist_ok=True)
