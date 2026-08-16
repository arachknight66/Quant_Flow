from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog, asyncio, time, uvicorn
from backend.core.config import settings
from backend.core.database import engine, Base
from backend.api.routers import market, analysis, portfolio, auth, ws

log = structlog.get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting QuantPlatform API", version="0.1.0")
    is_sqlite = "sqlite" in settings.database_url
    if settings.DEBUG or is_sqlite:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            log.info("Database tables initialized")
        except Exception as e:
            log.warning("Database setup ran concurrently or skipped", error=str(e))
    log.info("Database ready")
    
    # Schedule background tasks
    polling_task = asyncio.create_task(ws.price_polling_task(poll_interval_seconds=5.0))
    log.info("Price polling task scheduled")
    
    from backend.services.model_retraining_service import model_retraining_loop
    retraining_task = asyncio.create_task(model_retraining_loop(poll_interval_hours=168.0))
    log.info("Model retraining task scheduled (weekly)")
    
    yield
    
    polling_task.cancel()
    retraining_task.cancel()
    
    try:
        await asyncio.gather(polling_task, retraining_task, return_exceptions=True)
    except Exception as e:
        log.warning("Error gathering background tasks on shutdown", error=str(e))
        
    await engine.dispose()

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME, version="0.1.0",
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        lifespan=lifespan,
    )
    app.add_middleware(CORSMiddleware, allow_origins=settings.ALLOWED_ORIGINS,
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    from backend.middleware.timing import PerformanceBudgetMiddleware
    app.add_middleware(PerformanceBudgetMiddleware)

    from backend.middleware.csrf import CSRFHeaderMiddleware
    app.add_middleware(CSRFHeaderMiddleware)

    try:
        from prometheus_fastapi_instrumentator import Instrumentator
        Instrumentator().instrument(app).expose(app, endpoint="/metrics")
    except Exception as e:
        log.warning("Prometheus instrumentator setup skipped", error=str(e))

    from backend.core.limiter import limiter
    from slowapi.errors import RateLimitExceeded
    from slowapi import _rate_limit_exceeded_handler
    from backend.middleware.rate_limit import SlowAPIMiddleware
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    from fastapi.exceptions import RequestValidationError
    from pydantic import ValidationError

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        if isinstance(exc, (RequestValidationError, ValidationError)):
            return JSONResponse(status_code=422, content={"detail": str(exc)})
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(RuntimeError)
    async def runtime_error_handler(request: Request, exc: RuntimeError):
        log.error("Runtime error", error=str(exc))
        return JSONResponse(status_code=500, content={"detail": "Internal error"})

    app.include_router(auth.router,      prefix=f"{settings.API_V1_PREFIX}/auth",      tags=["auth"])
    app.include_router(market.router,    prefix=f"{settings.API_V1_PREFIX}/market",    tags=["market"])
    app.include_router(analysis.router,  prefix=f"{settings.API_V1_PREFIX}/analysis",  tags=["analysis"])
    app.include_router(portfolio.router, prefix=f"{settings.API_V1_PREFIX}/portfolio", tags=["portfolio"])
    
    from backend.api.routers import monitoring
    app.include_router(monitoring.router, prefix=f"{settings.API_V1_PREFIX}/monitoring", tags=["monitoring"])

    from backend.api.routers import notifications
    app.include_router(notifications.router, prefix=f"{settings.API_V1_PREFIX}/notifications", tags=["notifications"])
    
    app.include_router(ws.router, prefix="/ws", tags=["streaming"])

    @app.get("/health")
    async def health_check():
        return {"status": "ok", "timestamp": time.time()}

    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator().instrument(app).expose(app, endpoint="/metrics")

    return app

app = create_app()

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000,
                reload=settings.DEBUG, workers=1 if settings.DEBUG else 4)
