import time, structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

log = structlog.get_logger()

LATENCY_BUDGETS = {
    "/api/v1/analysis/analyze": 500,
    "/api/v1/analysis/backtest": 30_000,
    "/api/v1/market/ohlcv": 200,
    "/api/v1/auth/": 100,
}

class PerformanceBudgetMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            method=request.method, path=request.url.path,
            client_ip=request.client.host if request.client else "unknown")
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Response-Time-Ms"] = str(round(duration_ms, 1))
        for pattern, budget in LATENCY_BUDGETS.items():
            if request.url.path.startswith(pattern):
                if duration_ms > budget:
                    log.warning("Performance budget exceeded", path=request.url.path,
                                duration_ms=round(duration_ms,1), budget_ms=budget)
                break
        return response
