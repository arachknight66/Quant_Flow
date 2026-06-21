# backend/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyHttpUrl, field_validator, model_validator
from typing import List
import warnings


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

    @model_validator(mode="after")
    def _warn_on_insecure_prod_origins(self) -> "Settings":
        """
        PHASE 2.2 FIX: previously there was no check at all linking
        DEBUG to ALLOWED_ORIGINS. The default ALLOWED_ORIGINS list
        contains localhost dev origins, and if an operator deployed to
        production with DEBUG=False but forgot to override
        ALLOWED_ORIGINS in their environment, the API would happily
        serve CORS headers permitting requests from
        http://localhost:3000 in production — which is harmless on its
        own (nobody's browser is actually running on the prod server's
        localhost) but is a strong signal of a forgotten override, and
        in some misconfigured deployments (e.g. an operator's local
        reverse proxy tunnelled to "localhost" against the prod API)
        it can become exploitable. This fails loudly at startup instead
        of silently shipping a half-configured CORS policy.

        Deliberately a warning, not a hard crash: some legitimate setups
        (single-developer staging boxes, docker-compose smoke tests with
        DEBUG=False) do want localhost reachable in non-debug mode, so we
        don't want to brick those. But it must never pass silently.
        """
        if not self.DEBUG:
            localhost_origins = [
                o for o in self.ALLOWED_ORIGINS
                if "localhost" in o or "127.0.0.1" in o
            ]
            if localhost_origins:
                warnings.warn(
                    f"ALLOWED_ORIGINS contains localhost/127.0.0.1 entries "
                    f"({localhost_origins}) while DEBUG=False. If this is a "
                    f"production deployment, set ALLOWED_ORIGINS to your "
                    f"actual domain(s) via environment variable. If this is "
                    f"intentional (staging, local smoke test), this warning "
                    f"is safe to ignore.",
                    UserWarning,
                    stacklevel=2,
                )
        return self


# Singleton — import this everywhere
settings = Settings()