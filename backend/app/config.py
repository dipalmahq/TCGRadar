from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RADAR_", env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://radar:radar@localhost:5432/radar"
    database_pool_size: int = Field(default=5, ge=1, le=20)
    database_max_overflow: int = Field(default=5, ge=0, le=20)
    environment: str = "development"
    api_key: str = ""
    shops_file: Path = Path("config/shops.json")
    frontend_dir: Path = Path("frontend/dist")
    user_agent: str = "JoyBoyzTCGRadar/0.1 (private TCG availability monitor)"
    request_delay_seconds: float = 2.0
    request_timeout_seconds: float = 25.0
    worker_tick_seconds: int = 5
    worker_concurrency: int = 4
    refresh_batch_size: int = 12
    refresh_interval_seconds: int = Field(default=1800, ge=60)
    watch_interval_seconds: int = Field(default=300, ge=60)
    notification_tick_seconds: int = Field(default=1, ge=1)
    stale_after_minutes: int = 1440
    history_retention_days: int = 90
    discord_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    notifications_enabled: bool = False
    log_level: str = "INFO"

    @model_validator(mode="after")
    def require_production_key(self):
        if self.environment == "production" and len(self.api_key) < 32:
            raise ValueError("RADAR_API_KEY must have at least 32 characters in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
