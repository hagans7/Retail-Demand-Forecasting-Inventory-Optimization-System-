"""Training routes — POST /training/trigger, GET /training/status/{job_id}."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.core.logging.logger import get_logger

router = APIRouter(prefix="/training", tags=["MLOps"])
_logger = get_logger(__name__)


class TrainingTriggerRequest(BaseModel):
    run_date: str | None = None
    reason  : str        = "Manual trigger"


class TrainingTriggerResponse(BaseModel):
    job_id  : str
    status  : str
    message : str


class TrainingStatusResponse(BaseModel):
    job_id  : str
    status  : str
    result  : dict | None = None


@router.post("/trigger", response_model=TrainingTriggerResponse,
             summary="Manually trigger LightGBM training pipeline")
async def trigger_training(request: TrainingTriggerRequest) -> TrainingTriggerResponse:
    """Trigger training pipeline manually (bypasses cooldown check).

    Dispatches Celery task. Returns job_id for status polling.
    Training runs all 3 quantiles (q40, q60, q80) in sequence.
    Promotion to production happens automatically if model beats naive by 30%.
    """
    try:
        from src.worker import training_task
        result = training_task.delay(run_date=request.run_date)
        _logger.info("Training triggered",
                     extra={"job_id": result.id, "reason": request.reason,
                            "operation": "trigger_training"})
        return TrainingTriggerResponse(
            job_id=result.id,
            status="dispatched",
            message=f"Training task dispatched. Poll /training/status/{result.id}",
        )
    except Exception as e:
        _logger.error("Training trigger failed", exc_info=True)
        raise HTTPException(status_code=503, detail=f"Could not dispatch training task: {e}")


@router.get("/status/{job_id}", response_model=TrainingStatusResponse,
            summary="Check training task status")
async def get_training_status(job_id: str) -> TrainingStatusResponse:
    """Poll Celery task status for a training job.

    States: PENDING → STARTED → SUCCESS | FAILURE.
    On SUCCESS, result contains version_tag, promoted flag, and validation metrics.
    """
    try:
        from src.worker import app as celery_app
        task   = celery_app.AsyncResult(job_id)
        status = task.status
        result = task.result if task.ready() else None
        if isinstance(result, Exception):
            result = {"error": str(result)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Could not check task status: {e}")

    return TrainingStatusResponse(job_id=job_id, status=status, result=result)
