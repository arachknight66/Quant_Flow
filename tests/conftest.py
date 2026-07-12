import os
import pytest
import asyncio
import fnmatch

os.environ["SECRET_KEY"] = "extremely-long-random-string-used-for-testing-purposes-only-no-trivial-patterns"
os.environ["POSTGRES_PASSWORD"] = "testpassword"
os.environ["DEBUG"] = "True"

import bcrypt
if not hasattr(bcrypt, "__about__"):
    class FakeAbout:
        __version__ = bcrypt.__version__
    bcrypt.__about__ = FakeAbout()

import uuid
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Patch PGUUID to handle python UUID objects as strings on SQLite
original_bind_processor = PGUUID.bind_processor
def sqlite_bind_processor(self, dialect):
    if dialect.name == "sqlite":
        return lambda value: str(value) if value is not None else None
    return original_bind_processor(self, dialect)
PGUUID.bind_processor = sqlite_bind_processor

original_result_processor = PGUUID.result_processor
def sqlite_result_processor(self, dialect, coltype):
    if dialect.name == "sqlite":
        return lambda value: uuid.UUID(value) if value is not None else None
    return original_result_processor(self, dialect, coltype)
PGUUID.result_processor = sqlite_result_processor

from backend.core.database import Base, get_db
from backend.main import create_app
from httpx import AsyncClient, ASGITransport
import backend.models
from sqlalchemy.orm import configure_mappers
try:
    configure_mappers()
except Exception as e:
    import traceback
    traceback.print_exc()

# Compile overrides to make PG JSONB and UUID work on SQLite for testing
from sqlalchemy import BigInteger

@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(element, compiler, **kw):
    return "JSON"

@compiles(PGUUID, "sqlite")
def compile_uuid_sqlite(element, compiler, **kw):
    return "CHAR(36)"

@compiles(BigInteger, "sqlite")
def compile_bigint_sqlite(element, compiler, **kw):
    return "INTEGER"

# SQLite file-based engine for persistence across connections
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_temp.db"
engine = create_async_engine(TEST_DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

import backend.core.database
backend.core.database.engine = engine
backend.core.database.AsyncSessionLocal = AsyncSessionLocal

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    policy = asyncio.get_event_loop_policy()
    res_loop = policy.new_event_loop()
    yield res_loop
    res_loop.close()

@pytest.fixture(scope="session")
async def db_engine():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    import os
    if os.path.exists("./test_temp.db"):
        try:
            os.remove("./test_temp.db")
        except Exception:
            pass

@pytest.fixture
async def db_session(db_engine) -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()

class MockRedis:
    def __init__(self):
        self.store = {}
    async def get(self, key):
        val = self.store.get(key)
        if val is None:
            return None
        return val.encode("utf-8") if isinstance(val, str) else val
    async def setex(self, key, expiry, value):
        self.store[key] = value
        return True
    async def delete(self, key):
        if key in self.store:
            del self.store[key]
            return 1
        return 0
    async def scan_iter(self, match=None, count=100):
        keys = list(self.store.keys())
        if match:
            # simple glob matching
            keys = [k for k in keys if fnmatch.fnmatch(k, match)]
        for k in keys:
            yield k
    async def ping(self):
        return True

@pytest.fixture
def mock_redis(monkeypatch):
    r = MockRedis()
    async def mock_get_redis():
        return r
    monkeypatch.setattr("backend.services.market_data_service.get_redis", mock_get_redis)
    return r

@pytest.fixture
async def app_client(db_session) -> AsyncClient:
    app = create_app()
    # Override get_db to return the test session
    async def override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
