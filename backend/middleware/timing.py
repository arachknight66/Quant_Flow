# backend/middleware/timing.py
"""
Request timing middleware with performance budget enforcement.

Target latencies (p95):
  - Cached analysis response:         < 50ms
  - Uncached analysis (DB hit):       < 200ms
  - Analysis with API fetch:          < 2000ms (yfinance is slow)
  - Backtest (1 year daily):          < 10s (background task in prod)
  - WebSocket message delivery:       < 100ms

Latency breakdown for analysis endpoint:
  Redis cache hit:     ~5ms
  PostgreSQL query:    ~20ms
  Feature computation: ~50ms  (pandas, ~252 rows)
  GARCH fit:           ~100ms (first request; cached after)
  HMM inference:       ~10ms  (pre-fitted)
  XGBoost inference:   ~2ms   (single row)
  Risk engine:         ~1ms
  Monte Carlo 10k:     ~80ms  (numpy vectorised)
  Total (no cache):    ~268ms ✓

Optimisations applied:
  1. Prediction cache (30s) — most common case hits this
  2. Feature cache — don't recompute if data unchanged
  3. GARCH model cache — refit weekly, not per request
  4. Thread pool for CPU-bound ML ops (non-blocking event loop)
  5. Redis pipeline for multi-key operations
"""
import time
import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

log = structlog.get_logger()

# Performance budget in milliseconds
LATENCY_BUDGETS = {
    "/api/v1/analysis/analyze": 500,
    "/api/v1/analysis/backtest": 30_000,
    "/api/v1/market/ohlcv": 200,
    "/api/v1/auth/": 100,
    "/ws/": None,  # No budget for WebSocket
}


class PerformanceBudgetMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()

        # Bind request context for all log messages in this request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            method=request.method,
            path=request.url.path,
            client_ip=request.client.host if request.client else "unknown",
        )

        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        response.headers["X-Response-Time-Ms"] = str(round(duration_ms, 1))

        # Check budget
        for pattern, budget in LATENCY_BUDGETS.items():
            if budget and request.url.path.startswith(pattern):
                if duration_ms > budget:
                    log.warning(
                        "Performance budget exceeded",
                        path=request.url.path,
                        duration_ms=round(duration_ms, 1),
                        budget_ms=budget,
                        overage_pct=round((duration_ms / budget - 1) * 100, 1),
                    )
                break

        log.info(
            "Request complete",
            status=response.status_code,
            duration_ms=round(duration_ms, 1),
        )

        return response