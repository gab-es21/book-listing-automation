from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class Settings(BaseSettings):
    PHOTOS_PER_BOOK: int = 2
    RAW_DIR: str = "photos_raw"
    GROUPED_DIR: str = "photos_grouped"
    DB_URL: str = "sqlite:///./blt.db"
    TZ: str = "Europe/Lisbon"

    # Preço fixo (sem negociação mencionada na descrição - é tratada à parte,
    # e o transporte é gerido pelo próprio Vinted, não é referido aqui)
    BOOK_PRICE_EUR: float = 7.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
os.makedirs(settings.RAW_DIR, exist_ok=True)
os.makedirs(settings.GROUPED_DIR, exist_ok=True)
