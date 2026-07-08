from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from typing import List
import warnings

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )
    APP_NAME: str = "QuantPlatform"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:19006"]
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str = "quantplatform"
    POSTGRES_PORT: int = 5432
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None
    ALPHA_VANTAGE_API_KEY: str | None = None
    BINANCE_API_KEY: str | None = None
    BINANCE_SECRET_KEY: str | None = None
    MODEL_ARTIFACTS_DIR: str = "./ml/artifacts"
    FEATURE_LOOKBACK_DAYS: int = 252
    RATE_LIMIT_PER_MINUTE: int = 60

    @property
    def database_url(self) -> str:
        return (f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}")

    @property
    def sync_database_url(self) -> str:
        return (f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}")

    @model_validator(mode="after")
    def _warn_on_insecure_prod_origins(self) -> "Settings":
        if not self.DEBUG:
            localhost_origins = [o for o in self.ALLOWED_ORIGINS
                                 if "localhost" in o or "127.0.0.1" in o]
            if localhost_origins:
                warnings.warn(
                    f"ALLOWED_ORIGINS contains localhost entries {localhost_origins} "
                    f"while DEBUG=False. Set ALLOWED_ORIGINS to your production domain.",
                    UserWarning, stacklevel=2,
                )
        return self

settings = Settings()
