# backend/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyHttpUrl, field_validator
from typing import List


class Settings(BaseSettings):
    """
    All configuration comes from environment variables or .env file.
    Never hardcode secrets. Pydantic-settings validates types at startup.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    APP_NAME: str = "QuantPlatform"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    SECRET_KEY: str  # REQUIRED — no default, fails loudly if missing
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # CORS — restrict in production to your actual domain
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:19006"]

    # Database
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str  # REQUIRED
    POSTGRES_DB: str = "quantplatform"
    POSTGRES_PORT: int = 5432

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def sync_database_url(self) -> str:
        # Used by Alembic migrations (sync driver)
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None

    # External APIs
    ALPHA_VANTAGE_API_KEY: str | None = None
    BINANCE_API_KEY: str | None = None
    BINANCE_SECRET_KEY: str | None = None

    # ML
    MODEL_ARTIFACTS_DIR: str = "./ml/artifacts"
    FEATURE_LOOKBACK_DAYS: int = 252  # 1 trading year

    # Rate limiting (requests per minute per user)
    RATE_LIMIT_PER_MINUTE: int = 60


# Singleton — import this everywhere
settings = Settings()