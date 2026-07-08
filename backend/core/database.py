from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from backend.core.config import settings
import structlog

log = structlog.get_logger()

class Base(DeclarativeBase):
    pass

engine = create_async_engine(
    settings.database_url, pool_pre_ping=True, pool_size=10,
    max_overflow=20, echo=settings.DEBUG,
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False,
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
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
