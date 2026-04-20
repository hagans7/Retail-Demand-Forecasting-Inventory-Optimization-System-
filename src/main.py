"""FastAPI application entrypoint — Retail Decision Intelligence Platform.

Startup sequence:
    1. Configure logging (before any service instantiation)
    2. Register all routes (V1 + V2)
    3. Serve via uvicorn

All 15+ endpoints registered:
    /forecast/              — 7-day forecast, confidence, explain, override
    /replenishment/         — restock recommendation
    /simulate-promo/roi     — V2 Decision Intelligence pipeline
    /simulate-promo/        — basic V1 promo simulation
    /analytics/*            — revenue, promo-effectiveness, price-sensitivity,
                              exceptions, summary, store/{id}, cannibalization/{id}
    /training/              — trigger, status
    /config/                — business-rules (GET/PATCH)
    /health                 — full V1+V2 health metrics
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Set minimal env defaults for import-time settings validation
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/1")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin123")
os.environ.setdefault("MODEL_STORE_BUCKET", "ml-models")

from src.core.config.settings import settings
from src.core.logging.log_config import configure_logging

configure_logging(log_env=settings.log_env)

from src.core.logging.logger import get_logger

_logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _logger.info(
        "Application starting",
        extra={"app": settings.app_name, "version": settings.app_version,
               "log_env": settings.log_env, "operation": "startup"},
    )
    yield
    _logger.info("Application shutting down", extra={"operation": "shutdown"})


def create_app() -> FastAPI:
    app = FastAPI(
        title="Retail Platform",
        version="1.0.0",
        description=(
            "One unified system: Forecast Engine + Decision Intelligence"
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Register all routes ────────────────────────────────────────────────
    from src.api.routes.health_routes      import router as health_router
    from src.api.routes.config_routes      import router as config_router
    from src.api.routes.forecast_routes    import router as forecast_router
    from src.api.routes.replenishment_routes import router as replenishment_router
    from src.api.routes.analytics_routes   import router as analytics_router
    from src.api.routes.simulation_routes  import router as simulation_router
    from src.api.routes.training_routes    import router as training_router
    from src.api.routes.bootstrap_routes   import router as bootstrap_router

    app.include_router(health_router)
    app.include_router(config_router)
    app.include_router(forecast_router)
    app.include_router(replenishment_router)
    app.include_router(analytics_router)
    app.include_router(simulation_router)
    app.include_router(training_router)
    app.include_router(bootstrap_router)

    return app


app = create_app()
