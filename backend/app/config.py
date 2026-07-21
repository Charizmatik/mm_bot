from decimal import Decimal
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    dry_run: bool = True
    database_url: str = "sqlite+aiosqlite:///./market_maker.sqlite3"
    mexc_api_key: str = ""
    mexc_api_secret: str = ""
    cors_origins: str = "http://localhost:5173,http://localhost:8080"
    engine_tick_seconds: float = 1.0
    quote_stale_seconds: float = 10.0
    balance_refresh_seconds: float = 10.0
    paper_maker_fee_pct: Decimal = Decimal("0.1")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
