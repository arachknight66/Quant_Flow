# backend/core/logging.py
"""
Structured logging setup with structlog.

In production, logs are JSON-formatted for ingestion by
log aggregation tools (Datadog, Grafana Loki, ELK stack).

In development, logs are human-readable with colors.

Why structlog over standard logging?
  - Native key-value context binding (no string formatting)
  - Processors pipeline (add timestamps, request IDs, etc.)
  - Async-safe context variables
  - Easy to add per-request context (correlation ID, user ID)
"""
import logging
import sys
import structlog
from backend.core.config import settings


def configure_logging():
    """
    Configure structlog processors pipeline.
    Call once at application startup.
    """
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.DEBUG:
        # Human-readable in development
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    else:
        # JSON in production (parse with Datadog/Loki/ELK)
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if settings.DEBUG else logging.INFO
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Redirect stdlib logging to structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.DEBUG if settings.DEBUG else logging.INFO,
    )

    # Silence noisy libraries
    for lib in ["uvicorn.access", "sqlalchemy.engine", "yfinance"]:
        logging.getLogger(lib).setLevel(
            logging.WARNING if not settings.DEBUG else logging.DEBUG
        )