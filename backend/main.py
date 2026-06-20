# backend/main.py
"""
FastAPI application entrypoint.

Architecture decisions:
- Lifespan context manager for startup/shutdown (modern FastAPI pattern)
- Structured JSON logging (structlog)
- Global exception handlers
- Health check endpoints for load balancer
- OpenAPI docs disabled in production
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
import structlog
import asyncio
import time
import uvicorn

from backend.core.config import settings
from backend.core.database import engine, Base
from backend.api.routers import market, analysis, portfolio, auth, ws

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup and shutdown logic.
    - Create DB tables (use Alembic migrations in production)
    - Warm up Redis connection pool
    - Load ML models into memory
    - Start the background price-polling task that feeds WebSocket clients

    PHASE 2.1 FIX: backend/api/routers/ws.py defines price_polling_task(),
    which is the only thing that ever calls
    ConnectionManager.broadcast_to_symbol() and therefore the only thing
    that makes the /ws/prices WebSocket endpoint actually useful. It was
    written but never scheduled anywhere in the app. The previous
    behaviour: a client could open a WebSocket connection, send
    {"action": "subscribe", "symbol": "AAPL"}, get back a "subscribed"
    acknowledgement... and then receive nothing, forever, because no
    process was ever polling prices or broadcasting them. This was the
    quietest possible failure mode — no error, no crash, just permanent
    silence on a feature that looked fully wired from the client's
    perspective. Fixed by creating the task here and cancelling it
    cleanly on shutdown so it doesn't leak across reloads/restarts.
    """
    log.info("Starting QuantPlatform API", version="0.1.0")

    # In development, create tables directly
    # In production, use Alembic: alembic upgrade head
    if settings.DEBUG:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    log.info("Database ready")

    # Start background price polling for WebSocket streaming.
    # asyncio.create_task() schedules it on the running event loop without
    # blocking startup — the app becomes ready to serve requests immediately
    # while this loop runs concurrently in the background.
    polling_task = asyncio.create_task(ws.price_polling_task(poll_interval_seconds=5.0))
    log.info("Price polling task scheduled")

    yield  # Application runs here

    log.info("Shutting down QuantPlatform API")

    # Cancel the background task cleanly. Without this, on reload (DEBUG mode
    # with --reload) or graceful shutdown, the old polling loop keeps running
    # as an orphaned task pinned to a closed event loop, which either leaks
    # memory/connections or raises noisy "Task was destroyed but it is
    # pending" warnings in logs.
    polling_task.cancel()
    try:
        await polling_task
    except asyncio.CancelledError:
        pass

    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        # Disable docs in production — they expose your API surface
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        lifespan=lifespan,
    )

    # ---- Middleware ----
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # Request timing middleware (helps identify slow endpoints)
    @app.middleware("http")
    async def add_process_time_header(request: Request, call_next):
        start_time = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start_time
        response.headers["X-Process-Time"] = str(round(duration * 1000, 2))
        if duration > 1.0:  # Log slow requests
            log.warning(
                "Slow request",
                path=request.url.path,
                duration_ms=round(duration * 1000, 2)
            )
        return response

    # ---- Global exception handlers ----
    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(RuntimeError)
    async def runtime_error_handler(request: Request, exc: RuntimeError):
        log.error("Runtime error", error=str(exc), path=request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal error"})

    # ---- Routes ----
    app.include_router(auth.router, prefix=f"{settings.API_V1_PREFIX}/auth", tags=["auth"])
    app.include_router(market.router, prefix=f"{settings.API_V1_PREFIX}/market", tags=["market"])
    app.include_router(analysis.router, prefix=f"{settings.API_V1_PREFIX}/analysis", tags=["analysis"])
    app.include_router(portfolio.router, prefix=f"{settings.API_V1_PREFIX}/portfolio", tags=["portfolio"])
    app.include_router(ws.router, prefix="/ws", tags=["streaming"])

    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "version": "0.1.0"}

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        workers=1 if settings.DEBUG else 4,
    )