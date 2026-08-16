from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from typing import List
import warnings
import os

print("VERCEL DEBUG os.environ keys:", list(os.environ.keys()))
print("VERCEL DEBUG POSTGRES_SERVER:", os.environ.get("POSTGRES_SERVER"))
print("VERCEL DEBUG REDIS_HOST:", os.environ.get("REDIS_HOST"))

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )
    APP_NAME: str = "QuantPlatform"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    SECRET_KEY: str = "default_placeholder_value_with_no_trivial_words_and_more_than_32_characters"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:19006",
        "https://quant-flow-web.vercel.app",
        "https://quant-flow-ten.vercel.app"
    ]
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "default_postgres_password_placeholder_value"
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

    @model_validator(mode="before")
    @classmethod
    def _parse_empty_strings(cls, data: dict) -> dict:
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v != ""}
        return data

    @model_validator(mode="after")
    def _validate_secret_key(self) -> "Settings":
        if len(self.SECRET_KEY) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")
        trivial = ["secret", "password", "changeme", "replace", "example", "12345", "qwerty"]
        if any(t in self.SECRET_KEY.lower() for t in trivial):
            raise ValueError("SECRET_KEY must not contain common/trivial substrings")
        return self

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
