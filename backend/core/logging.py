import logging, sys
import structlog
from backend.core.config import settings

def configure_logging():
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    processors = shared_processors + (
        [structlog.dev.ConsoleRenderer(colors=True)] if settings.DEBUG
        else [structlog.processors.format_exc_info, structlog.processors.JSONRenderer()]
    )
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if settings.DEBUG else logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(format="%(message)s", stream=sys.stdout,
                        level=logging.DEBUG if settings.DEBUG else logging.INFO)
    for lib in ["uvicorn.access", "sqlalchemy.engine", "yfinance"]:
        logging.getLogger(lib).setLevel(logging.WARNING if not settings.DEBUG else logging.DEBUG)
