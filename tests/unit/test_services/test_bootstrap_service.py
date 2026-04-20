
"""Tests — BootstrapService (Day-0 lifecycle orchestrator).

Mock strategy: each SQL query is routed by unique keyword patterns.
The service makes 4 distinct query types — routed by their unique SELECT columns:
  sales_transactions  → "min(date)"
  feature_snapshots   → "min(history_days)" (no space issue)
  model_registry      → "version_id" + "quantile_level"
  system_bootstrap    → "last_success_step"
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.services.bootstrap_service import (
    BootstrapService,
    TECHNICAL_MIN_DAYS,
    RECOMMENDED_MIN_DAYS,
)


def _make_service(
    sales_count: int = 4_565_000,
    date_min="2019-01-01",
    date_max="2023-12-31",
    n_pairs: int = 2500,
    min_days: int = 1826,
    production_model: dict | None = None,
    bucket_exists: bool = True,
):
    db    = MagicMock()
    redis = MagicMock()
    redis.set = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value=None)

    storage = MagicMock()
    storage.ensure_bucket = MagicMock(return_value=(not bucket_exists))
    storage.bucket_exists = MagicMock(return_value=bucket_exists)

    async def _execute(query, params=None):
        sql    = str(query).lower()
        result = MagicMock()

        if "sales_transactions" in sql:
            # _check_sales_data: COUNT(*), MIN(date), MAX(date)
            result.fetchone.return_value = (sales_count, date_min, date_max)

        elif "feature_snapshots" in sql:
            # _check_feature_coverage: n_pairs, max_days, pairs_technical, pairs_recommended, total_rows
            pairs_tech = n_pairs if min_days >= 35  else 0
            pairs_rec  = n_pairs if min_days >= 365 else 0
            result.fetchone.return_value = (n_pairs, min_days, pairs_tech, pairs_rec, n_pairs * min_days)

        elif "model_registry" in sql:
            # _get_production_model_info: 5-tuple
            if production_model:
                result.fetchone.return_value = (
                    production_model.get("version_id", "v1_test"),
                    production_model.get("version_tag", "v1_tag"),
                    production_model.get("val_mae_promo", 2.5),
                    production_model.get("promoted_at"),
                    production_model.get("trained_on_date", "2023-12-31"),
                )
            else:
                result.fetchone.return_value = None

        elif "system_bootstrap_status" in sql:
            result.fetchone.return_value = None

        else:
            result.fetchone.return_value = (0,)

        return result

    db.execute  = AsyncMock(side_effect=_execute)
    db.commit   = AsyncMock()
    db.rollback = AsyncMock()

    return BootstrapService(db_session=db, redis_client=redis, storage_client=storage)


# ── Smart Skip (Opti B) ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_skips_training_when_valid_model_exists():
    """Smart skip: valid model → train_model step must be 'skipped'."""
    prod = {"version_id": "v1_q60", "val_mae_promo": 2.5, "trained_on_date": "2023-12-31"}
    svc  = _make_service(production_model=prod)

    with patch("pipelines.training_pipeline.run", new_callable=AsyncMock) as mock_train:
        result = await svc.execute("t-001", force_retrain=False)

    mock_train.assert_not_called()
    step = next(s for s in result.steps if s.name == "train_model")
    assert step.status == "skipped"


@pytest.mark.asyncio
async def test_trains_when_no_production_model():
    """No model → training must be attempted."""
    svc = _make_service(production_model=None)

    with patch("pipelines.training_pipeline.run", new_callable=AsyncMock,
               return_value={"version_tag": "v_new", "promoted": True,
                             "results": {0.60: {"mae_promo": 2.45}}}):
        result = await svc.execute("t-002", force_retrain=False)

    step = next(s for s in result.steps if s.name == "train_model")
    assert step.status != "skipped"


@pytest.mark.asyncio
async def test_force_retrain_calls_training_even_if_model_valid():
    """force_retrain=True must call training pipeline regardless."""
    prod = {"version_id": "v1_q60", "val_mae_promo": 2.4, "trained_on_date": "2023-12-31"}
    svc  = _make_service(production_model=prod)

    backfill_result = {"status": "ok", "days_processed": 1826,
                       "pairs_written": 4565000, "skipped_days": 0, "elapsed_seconds": 1.0}
    train_result = {"version_tag": "v_forced", "promoted": True,
                    "results": {0.60: {"mae_promo": 2.3}}}

    with patch("pipelines.backfill_features_pipeline.run", new_callable=AsyncMock,
               return_value=backfill_result),          patch("pipelines.training_pipeline.run", new_callable=AsyncMock,
               return_value=train_result) as mock_train:
        await svc.execute("t-003", force_retrain=True)

    mock_train.assert_called_once()


# ── Readiness levels ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_technical_ready_at_35_days():
    """Exactly TECHNICAL_MIN_DAYS (35) → technical=True, recommended=False."""
    prod = {"version_id": "v1", "val_mae_promo": 2.5, "trained_on_date": "2019-02-05"}
    svc  = _make_service(min_days=TECHNICAL_MIN_DAYS, n_pairs=100, production_model=prod)

    result = await svc.execute("t-004", force_retrain=False)
    assert result.technical_ready is True
    assert result.recommended_ready is False


@pytest.mark.asyncio
async def test_recommended_ready_at_365_days():
    """≥365 days → both technical and recommended ready."""
    prod = {"version_id": "v1", "val_mae_promo": 2.5, "trained_on_date": "2023-12-31"}
    svc  = _make_service(min_days=RECOMMENDED_MIN_DAYS, n_pairs=100, production_model=prod)

    result = await svc.execute("t-005", force_retrain=False)
    assert result.technical_ready is True
    assert result.recommended_ready is True


@pytest.mark.asyncio
async def test_not_ready_below_35_days():
    """< TECHNICAL_MIN_DAYS → system blocked, backfill step fails."""
    svc    = _make_service(min_days=TECHNICAL_MIN_DAYS - 1, production_model=None)
    result = await svc.execute("t-005b", force_retrain=False)
    assert result.technical_ready is False
    assert result.is_ready is False


# ── Failure and partial success ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fails_at_step1_when_no_sales_data():
    """Empty sales → step 1 fails → resume_from='verify_sales_data'."""
    svc    = _make_service(sales_count=0)
    result = await svc.execute("t-006", force_retrain=False)

    step1 = next(s for s in result.steps if s.name == "verify_sales_data")
    assert step1.status == "failed"
    assert result.overall_status == "failed"
    assert result.resume_from == "verify_sales_data"
    assert result.is_ready is False


@pytest.mark.asyncio
async def test_training_crash_yields_partial_status():
    """Backfill ok, training crashes → overall=partial or failed (not success)."""
    svc = _make_service(production_model=None)

    with patch("pipelines.training_pipeline.run", new_callable=AsyncMock,
               side_effect=RuntimeError("OOM")):
        result = await svc.execute("t-007", force_retrain=False)

    assert result.overall_status in ("partial", "failed")
    assert result.is_ready is False


# ── Idempotency ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_backfill_skipped_when_coverage_sufficient():
    """≥35 days history → backfill pipeline never called."""
    prod = {"version_id": "v1", "val_mae_promo": 2.5, "trained_on_date": "2023-12-31"}
    svc  = _make_service(min_days=1826, production_model=prod)

    with patch("pipelines.backfill_features_pipeline.run", new_callable=AsyncMock) as mock_bf:
        result = await svc.execute("t-008", force_retrain=False)

    mock_bf.assert_not_called()
    step = next(s for s in result.steps if s.name == "backfill_features")
    assert step.status == "skipped"


@pytest.mark.asyncio
async def test_training_skipped_when_model_valid():
    """Valid model + sufficient coverage → training pipeline never called."""
    prod = {"version_id": "v1", "val_mae_promo": 2.5, "trained_on_date": "2023-12-31"}
    svc  = _make_service(min_days=1826, production_model=prod)

    with patch("pipelines.training_pipeline.run", new_callable=AsyncMock) as mock_train:
        await svc.execute("t-009", force_retrain=False)

    mock_train.assert_not_called()


# ── Structure invariants ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_always_5_steps_in_correct_order():
    """BootstrapResult always has exactly 5 steps in the correct sequence."""
    svc    = _make_service(sales_count=0)
    result = await svc.execute("t-010", force_retrain=False)

    assert len(result.steps) == 5
    assert [s.name for s in result.steps] == [
        "verify_sales_data", "create_minio_buckets",
        "backfill_features", "train_model", "mark_system_ready",
    ]


@pytest.mark.asyncio
async def test_notes_warn_when_technical_not_recommended():
    """technical=True but recommended=False → notes must explain accuracy implication."""
    prod = {"version_id": "v1", "val_mae_promo": 2.6, "trained_on_date": "2019-02-05"}
    svc  = _make_service(min_days=TECHNICAL_MIN_DAYS, n_pairs=100, production_model=prod)

    result = await svc.execute("t-011", force_retrain=False)

    if result.technical_ready and not result.recommended_ready:
        assert len(result.notes) > 0
        combined = " ".join(result.notes).lower()
        assert any(w in combined for w in ["accuracy", "technical", "recommended", "365", "lower"])