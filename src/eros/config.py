from functools import lru_cache
from pathlib import Path
from typing import Any
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración tipada de Eros Agent."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "development"
    log_level: str = "INFO"

    # Clave de autenticación para endpoints protegidos y panel de administración
    eros_api_key: str = ""

    # API de portafolio en producción (o localhost si se prueba en dev)
    portfolio_api_url: str = "https://api.mateogs.tech/api"

    # Telegram Bot
    telegram_bot_token: str = ""
    telegram_allowed_user_id: int | None = None

    @field_validator("telegram_allowed_user_id", mode="before")
    @classmethod
    def parse_optional_int(cls, v: Any) -> int | None:
        if v is None or v == "":
            return None
        return int(v)

    # LLM Providers
    gemini_api_key: str = ""
    anthropic_api_key: str = ""

    # Job Hunter thresholds
    match_min_score: int = 75

    # Storage
    database_path: str = "data/eros.db"

    @property
    def db_file_path(self) -> Path:
        p = Path(self.database_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


@lru_cache
def get_settings() -> Settings:
    return Settings()
