"""Logger factory — get_logger(__name__) in every class __init__.

Never configure logging at module level. Never use print() in production code.

Dev mode  (LOG_ENV=dev):  human-readable colored text → stdout only.
Prod mode (LOG_ENV=prod): JSON → two rotating files:
    logs/app-{YYYY-MM-DD}.log    → INFO+  (30-day retention)
    logs/error-{YYYY-MM-DD}.log  → ERROR  (90-day retention)
"""
from __future__ import annotations

import logging
import os


def get_logger(name: str) -> logging.Logger:
    """Return a configured Logger for the given module name.

    Call in every class __init__:
        self._logger = get_logger(__name__)

    All log calls must include extra={} with:
        - correlation_id (always)
        - service_name, operation (service layer)
        - store_id, item_id (when applicable)
        - simulation_id (decision layer)
    """
    return logging.getLogger(name)
