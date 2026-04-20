"""Celery application and task registry.

All pipeline tasks are registered here. Scheduled via celery beat.
Import lazily inside task bodies to avoid startup import errors.

Schedule (from blueprint):
    data_quality_gate       daily 00:30
    feature_engineering     daily 01:00
    batch_inference         daily 02:00
    forecast_evaluation     daily 08:00
    hypothesis_monitoring   weekly Mon 06:00
    analytics_snapshot      weekly Mon 07:00
    feedback_recalibration  weekly Mon 07:30
    model_challenger        monthly first Sunday 02:00
"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from src.core.config.settings import settings

app = Celery(
    "retail_decision_platform",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_max_retries=3,
    task_retry_backoff=True,
    task_retry_backoff_max=600,
    broker_connection_retry_on_startup=True,  # suppress CPendingDeprecationWarning
)

app.conf.beat_schedule = {
    "data-quality-gate": {
        "task": "src.worker.data_quality_gate_task",
        "schedule": crontab(hour=0, minute=30),
    },
    "feature-engineering": {
        "task": "src.worker.feature_engineering_task",
        "schedule": crontab(hour=1, minute=0),
    },
    "batch-inference": {
        "task": "src.worker.batch_inference_task",
        "schedule": crontab(hour=2, minute=0),
    },
    "forecast-evaluation": {
        "task": "src.worker.forecast_evaluation_task",
        "schedule": crontab(hour=8, minute=0),
    },
    "hypothesis-monitoring": {
        "task": "src.worker.hypothesis_monitoring_task",
        "schedule": crontab(hour=6, minute=0, day_of_week="monday"),
    },
    "analytics-snapshot": {
        "task": "src.worker.analytics_snapshot_task",
        "schedule": crontab(hour=7, minute=0, day_of_week="monday"),
    },
    "feedback-recalibration": {
        "task": "src.worker.feedback_recalibration_task",
        "schedule": crontab(hour=7, minute=30, day_of_week="monday"),
    },
    "model-challenger": {
        "task": "src.worker.model_challenger_task",
        "schedule": crontab(hour=2, minute=0, day_of_week="sunday", day_of_month="1-7"),
    },
}


# ── Task definitions ──────────────────────────────────────────────────────────

@app.task(name="src.worker.data_quality_gate_task", bind=True, max_retries=3)
def data_quality_gate_task(self, run_date: str | None = None):
    from pipelines.data_quality_gate_pipeline import run
    import asyncio
    asyncio.run(run(run_date=run_date))


@app.task(name="src.worker.feature_engineering_task", bind=True, max_retries=3)
def feature_engineering_task(self, run_date: str | None = None):
    from pipelines.feature_engineering_pipeline import run
    import asyncio
    asyncio.run(run(run_date=run_date))


@app.task(name="src.worker.batch_inference_task", bind=True, max_retries=3)
def batch_inference_task(self, run_date: str | None = None):
    from pipelines.batch_inference_pipeline import run
    import asyncio
    asyncio.run(run(run_date=run_date))


@app.task(name="src.worker.forecast_evaluation_task", bind=True, max_retries=3)
def forecast_evaluation_task(self, run_date: str | None = None):
    from pipelines.forecast_evaluation_pipeline import run
    import asyncio
    asyncio.run(run(run_date=run_date))


@app.task(name="src.worker.hypothesis_monitoring_task", bind=True, max_retries=3)
def hypothesis_monitoring_task(self, run_date: str | None = None):
    from pipelines.hypothesis_monitoring_pipeline import run
    import asyncio
    asyncio.run(run(run_date=run_date))


@app.task(name="src.worker.analytics_snapshot_task", bind=True, max_retries=3)
def analytics_snapshot_task(self, run_date: str | None = None):
    from pipelines.analytics_snapshot_pipeline import run
    import asyncio
    asyncio.run(run(run_date=run_date))


@app.task(name="src.worker.feedback_recalibration_task", bind=True, max_retries=3)
def feedback_recalibration_task(self, run_date: str | None = None):
    from pipelines.feedback_recalibration_pipeline import run
    import asyncio
    asyncio.run(run(run_date=run_date))


@app.task(name="src.worker.model_challenger_task", bind=True, max_retries=1)
def model_challenger_task(self, run_date: str | None = None):
    from pipelines.model_challenger_pipeline import run
    import asyncio
    asyncio.run(run(run_date=run_date))


@app.task(name="src.worker.training_task", bind=True, max_retries=1)
def training_task(self, run_date: str | None = None):
    from pipelines.training_pipeline import run
    import asyncio
    asyncio.run(run(run_date=run_date))


# @app.task(name="src.worker.backfill_features_task", bind=True, max_retries=1,
#           soft_time_limit=7200, time_limit=7800)  # 2hr soft / 2hr10m hard limit
# def backfill_features_task(
#     self,
#     start_date: str | None = None,
#     end_date:   str | None = None,
# ):
#     """Historical feature backfill — Day-0 bootstrap only.

#     Computes all 25 P1 features for every day in [start_date, end_date].
#     Time limit: 2 hours (for 4-year full backfill on modest hardware).
#     Idempotent: ON CONFLICT DO UPDATE makes re-running safe.
#     """
#     from pipelines.backfill_features_pipeline import run
#     import asyncio
#     return asyncio.run(run(start_date=start_date, end_date=end_date))


# @app.task(name="src.worker.bootstrap_task", bind=True, max_retries=1,
#           soft_time_limit=10800, time_limit=11400)  # 3hr soft / 3hr10m hard limit
# def bootstrap_task(self, force_retrain: bool = False):
#     """Day-0 bootstrap orchestrator — runs all initialization steps sequentially.

#     Steps (smart skip by default):
#         1. verify_sales_data
#         2. create_minio_buckets
#         3. backfill_features (skipped if sufficient coverage exists)
#         4. train_model (skipped if valid production model exists — Opti B)
#         5. mark_system_ready

#     force_retrain=True overrides step 4 smart skip.
#     Returns BootstrapResult.to_dict() for Celery result backend.
#     """
#     import asyncio
#     import uuid

#     async def _run():
#         import redis.asyncio as aioredis
#         from src.providers.infrastructure import _session_factory, get_storage_client
#         from src.services.bootstrap_service import BootstrapService

#         task_id = self.request.id or str(uuid.uuid4())
#         storage = get_storage_client()

#         async with _session_factory() as db:
#             redis = aioredis.from_url(
#                 "redis://redis:6379/0", decode_responses=True
#             )
#             svc    = BootstrapService(db, redis, storage)
#             result = await svc.execute(task_id=task_id, force_retrain=force_retrain)
#         return result.to_dict()

#     return asyncio.run(_run())



@app.task(name="src.worker.backfill_features_task", bind=True, max_retries=2,
          soft_time_limit=1800, time_limit=2100)  # 30min soft / 35min hard limit (bulk INSERT)
def backfill_features_task(
    self,
    start_date: str | None = None,
    end_date:   str | None = None,
):
    """Historical feature backfill — Day-0 bootstrap only.
 
    Computes all 25 P1 features for every day in [start_date, end_date].
    Time limit: 2 hours (for 4-year full backfill on modest hardware).
    Idempotent: ON CONFLICT DO UPDATE makes re-running safe.
    """
    from pipelines.backfill_features_pipeline import run
    import asyncio
    return asyncio.run(run(start_date=start_date, end_date=end_date))
 
 
@app.task(name="src.worker.bootstrap_task", bind=True, max_retries=1,
          soft_time_limit=3600, time_limit=3900)   # 1hr soft / 1hr5m hard limit
def bootstrap_task(self, force_retrain: bool = False):
    """Day-0 bootstrap orchestrator — runs all initialization steps sequentially.
 
    Steps (smart skip by default):
        1. verify_sales_data
        2. create_minio_buckets
        3. backfill_features (skipped if sufficient coverage exists)
        4. train_model (skipped if valid production model exists — Opti B)
        5. mark_system_ready
 
    force_retrain=True overrides step 4 smart skip.
    Returns BootstrapResult.to_dict() for Celery result backend.
    """
    import asyncio
    import uuid
 
    async def _run():
        import redis.asyncio as aioredis
        from src.providers.infrastructure import make_worker_session, get_storage_client
        from src.services.bootstrap_service import BootstrapService
 
        task_id = self.request.id or str(uuid.uuid4())
        storage = get_storage_client()
 
        async with make_worker_session() as db:
            redis = aioredis.from_url(
                "redis://redis:6379/0", decode_responses=True
            )
            svc    = BootstrapService(db, redis, storage)
            result = await svc.execute(task_id=task_id, force_retrain=force_retrain)
        return result.to_dict()
 
    return asyncio.run(_run())
 