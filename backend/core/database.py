# backend/core/database.py
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from backend.core.config import settings
import structlog

log = structlog.get_logger()


class Base(DeclarativeBase):
    """
    All SQLAlchemy ORM models inherit from this.
    Using DeclarativeBase (SQLAlchemy 2.0 style) for type safety.
    """
    pass


# Create async engine.
# pool_pre_ping=True validates connections before use — critical for
# production where DB connections can drop silently.
# pool_size and max_overflow control connection pool behaviour.
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=settings.DEBUG,  # SQL logging in dev only
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    # expire_on_commit=False means objects remain usable after commit
    # Important for async code where lazy loading doesn't work
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for database sessions.
    Uses async context manager to guarantee session cleanup.
    Never share a session across requests — one session per request.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context():
    """
    For use outside of FastAPI dependency injection
    (e.g. background tasks, CLI scripts, data pipeline).
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            log.exception("Database transaction failed, rolled back")
            raise
        finally:
            await session.close()