import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PHOTOS_PER_BOOK: int = 2
    RAW_DIR: str = "photos_raw"
    GROUPED_DIR: str = "photos_grouped"
    DB_URL: str = "sqlite:///./blt.db"
    TZ: str = "Europe/Lisbon"

    # Preço fixo (sem negociação mencionada na descrição - é tratada à parte,
    # e o transporte é gerido pelo próprio Vinted, não é referido aqui)
    BOOK_PRICE_EUR: float = 7.0

    # Modo de desenvolvimento: fotos raw nunca são apagadas/movidas (são
    # copiadas), group-all reinicia sempre os livros pending/failed em vez de
    # acumular, o Next da review não promove a available (avança ciclicamente
    # sem gastar a fila), e o extract reaproveita ISBNs já resolvidos antes de
    # voltar a bater na Almedina. Nunca mexe em livros available/sold_out.
    DEV_MODE: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
os.makedirs(settings.RAW_DIR, exist_ok=True)
os.makedirs(settings.GROUPED_DIR, exist_ok=True)
