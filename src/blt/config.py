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
    OLLAMA_FILTER_MODEL: str = "phi4-mini"

    # Preço fixo (sem negociação mencionada na descrição - é tratada à parte,
    # e o transporte é gerido pelo próprio Vinted, não é referido aqui)
    BOOK_PRICE_EUR: float = 7.0

    # Redimensionamento de imagens antes de enviar ao modelo de visão local
    VISION_MAX_SIDE: int = 1280
    VISION_JPEG_QUALITY: int = 85

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
os.makedirs(settings.RAW_DIR, exist_ok=True)
os.makedirs(settings.GROUPED_DIR, exist_ok=True)
