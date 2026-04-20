"""Feedback recalibration pipeline — weekly Monday 07:30.

Processes decision_simulations created 7-14 days ago (PENDING status).
Compares predicted vs actual promo outcomes.
Updates item_elasticity_observed via EMA (Category 4 parameters).
Writes simulation drift metrics to monitoring_metrics table.

CRITICAL GUARD: simulations where promo was not executed in-store
(promo=0 in actuals) → CANCELLED_IN_STORE → excluded from recalibration.
This prevents model poisoning from non-executed promos.

Category 4 parameters updated: item_elasticity_observed ONLY.
Model artifacts and Category 1-3 parameters are NOT modified.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

from src.core.config.settings import settings
from src.core.constants.decision_constants import (
    APPROVAL_SUCCESS_RATE_ALERT_THRESHOLD,
    OVERRIDE_RATE_WARNING_THRESHOLD,
)
from src.core.logging.logger import get_logger
from src.providers.infrastructure import _session_factory, get_redis_client

_logger = get_logger(__name__)


async def run(run_date: str | None = None) -> dict:
    """Entry point for feedback_recalibration_task (Celery)."""
    run_dt = datetime.now(tz=timezone.utc)
    _logger.info(
        "Feedback recalibration pipeline started",
        extra={"run_date": run_date, "pipeline_name": "feedback_recalibration"},
    )

    async with _session_factory() as db:
        redis = get_redis_client()

        from src.repositories.decision_repository import DecisionRepository
        from src.repositories.analytics_repository import AnalyticsRepository
        from src.repositories.elasticity_repository import ElasticityRepository
        from src.repositories.monitoring_repository import MonitoringRepository
        from src.services.update_decision_feedback import UpdateDecisionFeedbackService

        decision_repo    = DecisionRepository(db)
        analytics_repo   = AnalyticsRepository(db)
        elasticity_repo  = ElasticityRepository(db)
        monitoring_repo  = MonitoringRepository(db)

        feedback_service = UpdateDecisionFeedbackService(
            decision_repo=decision_repo,
            analytics_repo=analytics_repo,
            elasticity_repo=elasticity_repo,
        )

        # Run recalibration
        summary = await feedback_service.execute()

        # Compute and store simulation drift metrics
        drift = await decision_repo.get_simulation_drift_metrics(lookback_days=7)
        drift_metrics = {
            "decision_simulation_count_7d":          drift.get("n_simulations", 0),
            "decision_resolved_count_7d":            drift.get("n_resolved", 0),
            "decision_override_rate_7d":             drift.get("override_rate", 0.0),
            "decision_approval_success_rate_7d":     drift.get("approval_success_rate") or 0.0,
            "decision_roi_prediction_bias_7d":       drift.get("roi_prediction_bias") or 0.0,
            "decision_elasticity_recalibrations_7d": summary.get("n_resolved", 0),
            "decision_flagged_for_review":           summary.get("n_flagged", 0),
        }
        await monitoring_repo.save_daily_metrics(drift_metrics)

        # Alert checks
        override_rate = drift.get("override_rate", 0.0) or 0.0
        if override_rate > OVERRIDE_RATE_WARNING_THRESHOLD:
            _logger.warning(
                "High override rate — decision weights may need recalibration",
                extra={
                    "override_rate": override_rate,
                    "threshold": OVERRIDE_RATE_WARNING_THRESHOLD,
                    "pipeline_name": "feedback_recalibration",
                },
            )

        approval_success = drift.get("approval_success_rate") or 1.0
        if approval_success < APPROVAL_SUCCESS_RATE_ALERT_THRESHOLD and drift.get("n_resolved", 0) > 5:
            _logger.error(
                "ALERT: Low approval success rate — system approving unprofitable promos",
                extra={
                    "approval_success_rate": approval_success,
                    "threshold": APPROVAL_SUCCESS_RATE_ALERT_THRESHOLD,
                    "pipeline_name": "feedback_recalibration",
                },
            )

    _logger.info(
        "Feedback recalibration pipeline complete",
        extra={
            **summary,
            "pipeline_name": "feedback_recalibration",
            "elapsed_seconds": (datetime.now(tz=timezone.utc) - run_dt).total_seconds(),
        },
    )
    return summary


if __name__ == "__main__":
    asyncio.run(run())
