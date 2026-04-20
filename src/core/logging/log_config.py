"""Logging configuration — called once at application startup in main.py."""
from __future__ import annotations

import logging
import logging.config
import os
from pathlib import Path


def configure_logging(log_env: str = "dev") -> None:
    """Configure application-wide logging.

    Args:
        log_env: "dev" → stdout text; "prod" → JSON rotating files.

    Called by: src/main.py at startup before any service instantiation.
    """
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    if log_env == "prod":
        _configure_prod(log_dir)
    else:
        _configure_dev()


def _configure_dev() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    # Suppress noisy third-party loggers
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("lightgbm").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.INFO)


def _configure_prod(log_dir: Path) -> None:
    """JSON structured logs with daily rotation.

    General: logs/app-YYYY-MM-DD.log   (INFO+, 30-day retention)
    Errors:  logs/error-YYYY-MM-DD.log (ERROR, 90-day retention)
    """
    try:
        from pythonjsonlogger import jsonlogger  # type: ignore[import]
        json_formatter_class = "pythonjsonlogger.jsonlogger.JsonFormatter"
    except ImportError:
        # Fallback if python-json-logger not installed (should not happen in prod)
        json_formatter_class = "logging.Formatter"

    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": json_formatter_class,
                "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
            },
            "text": {
                "format": "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": "WARNING",
                "formatter": "text",
                "stream": "ext://sys.stdout",
            },
            "file_general": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "level": "INFO",
                "formatter": "json",
                "filename": str(log_dir / "app.log"),
                "when": "midnight",
                "backupCount": 30,
                "encoding": "utf-8",
            },
            "file_error": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "level": "ERROR",
                "formatter": "json",
                "filename": str(log_dir / "error.log"),
                "when": "midnight",
                "backupCount": 90,
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "src": {
                "level": "INFO",
                "handlers": ["console", "file_general", "file_error"],
                "propagate": False,
            },
            "pipelines": {
                "level": "INFO",
                "handlers": ["console", "file_general", "file_error"],
                "propagate": False,
            },
            "sqlalchemy.engine": {"level": "WARNING"},
            "lightgbm": {"level": "WARNING"},
            "celery": {
                "level": "INFO",
                "handlers": ["file_general", "file_error"],
                "propagate": False,
            },
        },
        "root": {
            "level": "WARNING",
            "handlers": ["console"],
        },
    }
    logging.config.dictConfig(config)
