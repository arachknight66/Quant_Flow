# alembic/env.py
"""
Alembic migration environment, configured for async SQLAlchemy + asyncpg.

CRITICAL FIX: this file was never written, so `alembic upgrade head` had
nothing to execute against. This is the single most blocking missing file
in the whole repo -- without it, the database schema literally cannot be
created, which means nothing else in the backend can run.

Two responsibilities:
  1. Import every ORM model so Base.metadata is fully populated (needed
     for --autogenerate to detect new tables/columns).
  2. Bridge Alembic's traditionally-sync migration runner to our async
     engine via run_sync().
"""
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from backend.core.database import Base
from backend.core.config import settings

# Import every ORM model here so they register on Base.metadata.
# Forgetting one means --autogenerate silently won't see its table.
from backend.models.user import User          # noqa: F401
from backend.models.asset import Asset        # noqa: F401
from backend.models.ohlcv import OHLCVData    # noqa: F401
from backend.models.signal import Signal      # noqa: F401

config = context.config

# Override sqlalchemy.url from our pydantic Settings, not the alembic.ini
# placeholder -- keeps secrets out of version control and in sync with
# whatever the app itself connects to.
config.set_main_option("sqlalchemy.url", settings.sync_database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection (`alembic upgrade head --sql`)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations against the live database using the asyncpg driver."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        url=settings.database_url,  # asyncpg URL, distinct from sync_database_url above
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()