import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PHOTOS_PER_BOOK: int = 2
    RAW_DIR: str = "photos_raw"
    GROUPED_DIR: str = "photos_grouped"
    # Scratch space for /bundle's "Criar pasta de capas" - a uniquely-named
    # subfolder of covers is created here per click, deleted again once you
    # confirm the bundle (or, if that never happens, on the next click - see
    # _cleanup_stale_bundle_tmp_dirs). Never anything worth keeping.
    BUNDLE_TMP_DIR: str = "bundle_tmp"
    DB_URL: str = "sqlite:///./blt.db"
    TZ: str = "Europe/Lisbon"

    # Preço fixo (sem negociação mencionada na descrição - é tratada à parte,
    # e o transporte é gerido pelo próprio Vinted, não é referido aqui)
    BOOK_PRICE_EUR: float = 8.0

    # Modo de desenvolvimento: fotos raw nunca são apagadas/movidas (são
    # copiadas), group-all reinicia sempre os livros pending/failed em vez de
    # acumular, o Next da review não promove a available (avança ciclicamente
    # sem gastar a fila), e o extract reaproveita ISBNs já resolvidos antes de
    # voltar a bater na Almedina. Nunca mexe em livros available/sold_out.
    DEV_MODE: bool = False

    # Webhook de um canal Discord para os botões "Enviar para Discord" em
    # /review e /stock. Vazio desativa-os (não é obrigatório).
    DISCORD_WEBHOOK_URL: str = ""

    # Bot token + ID de um canal Discord DEDICADO só para receber fotos raw
    # (nunca o mesmo canal do DISCORD_WEBHOOK_URL acima - senão o bot tentaria
    # reimportar as próprias fotos que ele mesmo publicou). Usados por
    # `blt fetch-discord-photos`; vazios desativa o comando (não é obrigatório).
    DISCORD_BOT_TOKEN: str = ""
    DISCORD_PHOTOS_CHANNEL_ID: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
os.makedirs(settings.RAW_DIR, exist_ok=True)
os.makedirs(settings.GROUPED_DIR, exist_ok=True)
os.makedirs(settings.BUNDLE_TMP_DIR, exist_ok=True)
