# Retail  Platform

---

## System Lifecycle States

```
STATE 0 — EMPTY          fresh deploy, no data
STATE 1 — DATA LOADED    sales_transactions filled
STATE 2 — FEATURES READY feature_snapshots backfilled (≥35 days per pair)
STATE 3 — MODEL TRAINED  production model in model_registry + MinIO
STATE 4 — READY          all 25 endpoints available

Fast check:  GET /health/readiness  → shows exactly which state you are in
Fast fix:    POST /bootstrap/run    → moves you from any state to STATE 4
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 1 — DATA FOUNDATION                                      │
│  sales_transactions · feature_snapshots                         │
│  item_financial_assumptions · item_elasticity_observed          │
│  system_bootstrap_status (lifecycle state tracking)             │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 2 — PREDICTIVE ENGINE (V1)                               │
│  data_quality_gate → feature_engineering → batch_inference      │
│  → forecast_evaluation → hypothesis_monitoring + feature_drift  │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 3 — DECISION INTELLIGENCE (V2)                           │
│  simulate_promo_roi orchestrator (10-step pipeline)             │
│  → uplift · uncertainty MC(N=1000) · cannibalization · score    │
│  → APPROVE / REVIEW / REJECT                                    │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 4 — FEEDBACK & LEARNING                                  │
│  feedback_recalibration (weekly) → EMA elasticity update        │
│  CANCELLED_IN_STORE guard (prevents model poisoning)            │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 5 — CONFIGURATION GOVERNANCE                             │
│  Cat 1: constants/*.py · Cat 2: .env · Cat 3: /config API       │
│  Cat 4: item_elasticity_observed (auto-learned weekly)          │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 6 — API (25 endpoints) + BOOTSTRAP PROTOCOL              │
│  /bootstrap · /health · /forecast · /replenishment              │
│  /analytics · /simulate-promo · /training · /config             │
└─────────────────────────────────────────────────────────────────┘
```

---

## Quick Start (TL;DR)

```bash
# 1. Start infrastructure
docker compose up --build -d

# 2. Run migrations
docker compose exec api alembic upgrade head

# 3. Load your sales data
docker compose cp notebooks/data/retail_sales.csv postgres:/tmp/retail_sales.csv
docker compose exec postgres psql -U platform_user -d retail_decision_dev -c "COPY sales_transactions(date,store_id,item_id,sales,price,promo,weekday,month) FROM '/tmp/retail_sales.csv' DELIMITER ',' CSV HEADER;"

# 4. Bootstrap everything (backfill + train + mark ready)
curl -X POST http://localhost:8000/bootstrap/run \
  -H "Content-Type: application/json" \
  -d '{"reason": "Initial bootstrap"}'

# 5. Poll until ready (takes 15-60 min for 4-year backfill + training)
curl http://localhost:8000/bootstrap/status?task_id={id_from_step_4}

# 6. Verify system ready
curl http://localhost:8000/health/readiness

# 7. Use any endpoint
curl -X POST http://localhost:8000/forecast/ \
  -H "Content-Type: application/json" \
  -d '{"store_id":"store_1","item_id":"item_6","promo_plan":[0,0,1,1,0,0,0],"price_plan":[20,20,16,16,20,20,20]}'
```

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.11.9 | Runtime |
| Docker + Compose | 27.x / v2.29+ | PostgreSQL, Redis, MinIO |
| uv (optional) | latest | Fast dependency install |

---

## Step 1 — Environment Setup

```bash
unzip retail_platform.zip && cd retail_platform

# Option A: uv (recommended)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv --python 3.11.9 .venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Option B: pip
python3.11 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip && pip install -e ".[dev]"

# Verify numpy/LightGBM (CRITICAL — numpy 2.x breaks LightGBM)
python -c "import lightgbm as lgb; import numpy as np; print(f'lgbm={lgb.__version__}, numpy={np.__version__}')"
# Expected: lgbm=4.6.0, numpy=1.26.x
# If numpy 2.x: pip install "numpy>=1.26.4,<2.0" --force-reinstall
```

---

## Step 2 — Environment Variables

```bash
cp .env.dev .env   # ready for local Docker use
```

`.env.dev` is pre-configured for Docker Compose internal network. When running API locally (not in Docker), change `minio:9000` → `localhost:9000` and `postgres:5432` → `localhost:5432`.

---

## Step 3 — Start Infrastructure

```bash
docker compose up --build -d

# Verify all services healthy
docker compose ps
# Expected: postgres (healthy), redis (healthy), minio (Up), api (Up), worker×2, scheduler, flower
```

---

## Step 4 — Run Database Migrations

```bash
# Apply all migrations (creates all tables + seeds required rows)
docker compose exec api alembic upgrade head

# Verify critical seed rows
docker compose exec postgres psql -U platform_user -d retail_decision_dev \
  -c "SELECT item_id, cogs_pct FROM item_financial_assumptions WHERE item_id='__default__';"
# Must show: __default__ | 0.6

docker compose exec postgres psql -U platform_user -d retail_decision_dev \
  -c "SELECT system_id, is_ready FROM system_bootstrap_status;"
# Must show: default | f   (not ready yet — expected)
```

---

## Step 5 — Run Test Suite

```bash
# 5.1 CRITICAL GATE — must pass before any deployment
python -m pytest tests/unit/test_pipelines/ -v
# Expected: 20/20 PASSED

# 5.2 Full unit tests
python -m pytest tests/unit/ -v
# Expected: 85+ PASSED

# 5.3 Integration tests (requires env vars)
export DATABASE_URL="postgresql+asyncpg://test:test@localhost:5432/test"
export REDIS_URL="redis://localhost:6379/0"
export CELERY_BROKER_URL="redis://localhost:6379/1"
export CELERY_RESULT_BACKEND="redis://localhost:6379/2"
export MINIO_ENDPOINT="localhost:9000"
export MINIO_ACCESS_KEY="test"
export MINIO_SECRET_KEY="testtest"
export MODEL_STORE_BUCKET="ml-models"
python -m pytest tests/integration/ -v

# 5.4 Complete suite
python -m pytest tests/ -v
# Expected: 95/95 PASSED
```

---

## Step 6 — Load Sales Data

```bash
# Copy CSV into PostgreSQL container
docker compose cp notebook/data/retail_sales.csv postgres:/tmp/retail_sales.csv

# Load into sales_transactions table
docker compose exec postgres psql -U platform_user -d retail_decision_dev -c \
  "COPY sales_transactions(date, store_id, item_id, sales, price, promo, weekday, month)
   FROM '/tmp/retail_sales.csv' DELIMITER ',' CSV HEADER;"

# Expected output: COPY 4565000
# If "duplicate key" error: data already loaded — this is fine, run SELECT below

# Verify data
docker compose exec postgres psql -U platform_user -d retail_decision_dev \
  -c "SELECT COUNT(*), MIN(date), MAX(date) FROM sales_transactions;"
# Expected: 4565000 | 2019-01-01 | 2023-12-31
```

---

## Step 7 — Bootstrap System (STATE 0 → STATE 4)

This is the critical step. Bootstrap does everything: backfill 4 years of features, train LightGBM, and mark system ready.

```bash
# Trigger bootstrap (async — returns immediately with task_id)
curl -X POST http://localhost:8000/bootstrap/run \
  -H "Content-Type: application/json" \
  -d '{"reason": "Initial system bootstrap"}'

# Response:
# {
#   "task_id": "abc123-...",
#   "status": "dispatched",
#   "message": "Bootstrap task dispatched. Backfill takes 15-60 minutes...",
#   "poll_url": "/bootstrap/status?task_id=abc123-..."
# }
```

### Monitor bootstrap progress

```bash
# Poll every 30 seconds
curl "http://localhost:8000/bootstrap/status?task_id=abc123-..."

# Response shows step-by-step progress:
# {
#   "overall_status": "running",
#   "is_ready": false,
#   "steps": [
#     {"name": "verify_sales_data",    "status": "success",  "message": "4,565,000 rows loaded"},
#     {"name": "create_minio_buckets", "status": "success",  "message": "Bucket 'ml-models' created"},
#     {"name": "backfill_features",    "status": "running",  "message": "..."},
#     {"name": "train_model",          "status": "pending",  "message": "not started"},
#     {"name": "mark_system_ready",    "status": "pending",  "message": "not started"}
#   ]
# }

# When complete, is_ready becomes true:
# {"overall_status": "success", "is_ready": true, "technical_ready": true, "recommended_ready": true}
```

### Bootstrap behavior — Smart Skip (Opti B)

Bootstrap is fully idempotent. It skips work already done:

| Condition | Behavior |
|-----------|---------|
| Feature coverage ≥ 35 days | Skip backfill |
| Valid production model exists | Skip training |
| `force_retrain=true` in request | Force training even if model valid |
| Run bootstrap again on ready system | All steps skipped — instant return |

```bash
# Force retrain (incident recovery / benchmark rebuild)
curl -X POST http://localhost:8000/bootstrap/run \
  -H "Content-Type: application/json" \
  -d '{"force_retrain": true, "reason": "Incident recovery — rebuild model from scratch"}'
```

---

## Step 8 — Verify System Ready

```bash
# Structured readiness checklist
curl http://localhost:8000/health/readiness

# Response when fully ready:
# {
#   "overall_ready": true,
#   "technical_ready": true,
#   "recommended_ready": true,
#   "next_action": "System FULLY READY — all endpoints available",
#   "checklist": {
#     "sales_data_loaded":              {"ok": true, "value": "4,565,000 rows (2019-01-01 → 2023-12-31)"},
#     "feature_snapshots_technical":    {"ok": true, "value": "2500 pairs, min_history=1826d (need ≥35d)"},
#     "feature_snapshots_recommended":  {"ok": true, "value": "min_history=1826d (recommended ≥365d)"},
#     "production_model_exists":        {"ok": true, "value": "v_20231231_abc123 (mae_promo=2.641)"},
#     "minio_bucket_exists":            {"ok": true, "value": "ml-models bucket accessible"}
#   }
# }

# Quick health check
curl http://localhost:8000/health
# system_ready: true means all endpoints available
```

### Readiness levels explained

| Level | Condition | Meaning |
|-------|-----------|---------|
| `technical_ready=true` | ≥35 days history per pair | Training can run, forecasts are functional |
| `recommended_ready=true` | ≥365 days history per pair | Model accuracy matches R&D baseline (MAE_promo 2.641) |
| `overall_ready=true` | technical + model + MinIO | All 25 endpoints fully operational |

If `technical_ready=true` but `recommended_ready=false`, all endpoints work but accuracy may be lower than the validated R&D baseline. This happens when sales data covers less than 1 year.

---

## Step 9 — All 25 Endpoints

Interactive documentation: **http://localhost:8000/docs** (Swagger UI)

### Bootstrap endpoints

```bash
# Run bootstrap (async dispatch)
POST /bootstrap/run
{"force_retrain": false, "reason": "Initial setup"}

# Check progress (works even after container restart)
GET /bootstrap/status?task_id={id}

# Detailed readiness checklist
GET /health/readiness
```

### Health

```bash
GET /health
# system_ready, model_version, rolling_7d_mae_promo, override_rate_7d
```

### Forecast (V1)

```bash
# 7-day demand forecast
POST /forecast/
{"store_id":"store_1","item_id":"item_6",
 "promo_plan":[0,0,1,1,0,0,0],
 "price_plan":[20,20,16,16,20,20,20]}

# 3-quantile confidence bands (q40/q60/q80)
POST /forecast/confidence
{"store_id":"store_1","item_id":"item_6",
 "promo_plan":[0,0,0,0,0,0,0],
 "price_plan":[20,20,20,20,20,20,20]}

# SHAP explanation in business language
POST /forecast/explain
{"store_id":"store_1","item_id":"item_6","target_date":"2026-04-21","promo":1,"price":16.0}

# Human planner override
POST /forecast/override
{"store_id":"store_1","item_id":"item_6","target_date":"2026-04-21",
 "override_qty":150,"reason":"Flash sale announced","user_id":"planner_001"}
```

### Replenishment

```bash
POST /replenishment/
{"store_id":"store_1","item_id":"item_6","current_stock":200,
 "promo_plan":[0,0,1,1,0,0,0],"price_plan":[20,20,16,16,20,20,20]}
# Returns: recommended_restock_qty, stockout_risk, stock_feasibility_score
```

### Promo Simulation (V1 + V2)

```bash
# Basic V1 — uplift only, no COGS
POST /simulate-promo/
{"store_id":"store_1","item_id":"item_6",
 "promo_dates":["2026-04-21","2026-04-22","2026-04-23"],
 "promo_price":16.0,"base_price":20.0}

# Full V2 Decision Intelligence
POST /simulate-promo/roi
{"store_id":"store_1","item_id":"item_6",
 "promo_dates":["2026-04-21","2026-04-22","2026-04-23"],
 "promo_price":16.0,"base_price":20.0,
 "current_stock":200,"cogs_pct":0.55,"promo_fixed_cost":200.0}
# Returns: APPROVE/REVIEW/REJECT + probability_profitable + uncertainty_band
```

**V2 validation rules:**
- `promo_price` must be strictly `<` `base_price` → HTTP 422 otherwise
- `promo_dates` max 14 days → HTTP 422 if exceeded
- All recommendations return HTTP 200 — system is decision support, not gate

### Analytics

```bash
GET /analytics/revenue               # unit vs revenue divergence (30.04pp baseline)
GET /analytics/promo-effectiveness   # item ranking by uplift (min 20 promo days)
GET /analytics/price-sensitivity/{item_id}  # per-item elasticity
GET /analytics/exceptions            # FORECAST_JUMP, ZERO_SALES, DEAD_STOCK ranked
GET /analytics/pareto                # revenue concentration (top 20% → ~30% revenue)
GET /analytics/drift                 # PSI-based feature drift (25 features)
GET /analytics/summary               # latest weekly snapshot
GET /analytics/store/{store_id}      # per-store growth profile
GET /analytics/cannibalization/{item_id}  # substitution + halo effect
```

### Configuration

```bash
# Read all Category 3 runtime parameters
GET /config/business-rules

# Update a parameter (audited, effective in 5 min)
PATCH /config/business-rules
{"config_key":"DECISION_APPROVE_THRESHOLD","config_value":0.80,
 "reason":"Q2 strategy: raise bar before peak season"}

# Read current decision weights
GET /config/decision-weights
```

**Configurable parameters and safety bounds:**

| Key | Bounds | Default |
|-----|--------|---------|
| `SAFETY_FACTOR_PROMO` | 1.0–2.0 | 1.20 |
| `SAFETY_FACTOR_NORMAL` | 1.0–1.5 | 1.10 |
| `SAFETY_FACTOR_COLD_START` | 1.0–2.0 | 1.30 |
| `DECISION_APPROVE_THRESHOLD` | 0.50–0.90 | 0.70 |
| `DECISION_REVIEW_THRESHOLD` | 0.20–0.60 | 0.40 |
| `DECISION_WEIGHT_ROI` | 0.10–0.70 | 0.40 |
| `DECISION_WEIGHT_STOCK` | 0.10–0.50 | 0.25 |
| `DECISION_WEIGHT_UNCERTAINTY` | 0.05–0.40 | 0.20 |
| `DECISION_WEIGHT_SUBSTITUTION` | 0.05–0.40 | 0.15 |

### Training / MLOps

```bash
# Manual training trigger
POST /training/trigger
{"reason":"Weekly challenger run"}
# Returns: {"job_id":"...","status":"dispatched"}

# Poll training status
GET /training/status/{job_id}
# Returns: {"status":"SUCCESS","result":{"version_tag":"...","promoted":true}}
```

---

## Step 10 — Pipeline Schedule

Pipelines run automatically via Celery Beat when all services are up.

| Pipeline | Schedule | Purpose |
|----------|----------|---------|
| `data_quality_gate` | Daily 00:30 | Pre-flight checks, blocks downstream if CRITICAL fails |
| `feature_engineering` | Daily 01:00 | Compute 25 features for today (steady-state) |
| `batch_inference` | Daily 02:00 | Forecast 2500 pairs in single vectorized predict() |
| `forecast_evaluation` | Daily 08:00 | Compare forecasts vs actuals, compute MAE |
| `hypothesis_monitoring` | Mon 06:00 | 4 automated hypothesis tests vs R&D baselines |
| `analytics_snapshot` | Mon 07:00 | Weekly aggregate business metrics |
| `feedback_recalibration` | Mon 07:30 | EMA elasticity update from promo actuals (V2) |
| `model_challenger` | Monthly Sun | Train challenger, compare champion, archival |

---

## Step 11 — Configuration Governance

| Category | What | Location | Who Changes | Process |
|---|---|---|---|---|
| 1 — Scientific | Model params, features, quantile | `src/core/constants/*.py` | Data scientist | PR + test gate + redeploy |
| 2 — Infrastructure | DB URL, Redis, MinIO | `.env` | DevOps | Env var + restart |
| 3 — Business Rules | Safety factors, decision weights | `business_configs` DB | Business analyst | `PATCH /config/business-rules` + reason |
| 4 — Learned | Item elasticity coefficients | `item_elasticity_observed` | Automated (weekly) | EMA via feedback pipeline |

---

## Step 12 — Troubleshooting

### `POST /bootstrap/run` → worker error: "No module named 'pipelines'"
```bash
# Root cause: PYTHONPATH not set
# Fix: docker-compose.yml must have PYTHONPATH: /app in x-common-env
# After updating docker-compose.yml:
docker compose down && docker compose up --build -d
```

### `/forecast/` → HTTP 503 "No production model"
```bash
# Check readiness
curl http://localhost:8000/health/readiness

# If production_model_exists = false → run bootstrap
curl -X POST http://localhost:8000/bootstrap/run \
  -d '{"reason":"train model"}' -H "Content-Type: application/json"
```

### Bootstrap stuck at backfill_features
```bash
# Check worker logs
docker compose logs worker --tail=50

# Check backfill progress
curl "http://localhost:8000/bootstrap/status?task_id=..."
# last_backfill_date shows current progress date

# If stuck, restart and resume
docker compose restart worker scheduler
curl -X POST http://localhost:8000/bootstrap/run \
  -d '{"reason":"resume after restart"}' -H "Content-Type: application/json"
# Smart skip will resume from last_backfill_date
```

### "duplicate key" error when loading CSV
```bash
# Not an error — data already loaded from a previous run
# Verify:
docker compose exec postgres psql -U platform_user -d retail_decision_dev \
  -c "SELECT COUNT(*) FROM sales_transactions;"
# If count > 0: data is fine, proceed to bootstrap
```

### Feature contract test fails
```
FAILED test_feature_contract.py::test_p1_feature_count_is_25
```
`feature_constants.py` was modified without R&D re-validation. Revert to 25-feature set. Never change Category 1 constants without data science review and test suite approval.

### Decision weights sum error
```
ConfigSafetyBoundsViolationError: DECISION_WEIGHTS do not sum to 1.0
```
Update the remaining `DECISION_WEIGHT_*` keys so they sum exactly to 1.0 before next simulation call.

### Celery `CPendingDeprecationWarning` in logs
Already fixed in `src/worker.py` (`broker_connection_retry_on_startup=True`). If still showing, rebuild containers: `docker compose up --build -d`.

---

## Step 13 — Monitoring

```bash
# Swagger UI
http://localhost:8000/docs

# Celery Flower (task monitoring)
http://localhost:5555

# MinIO console
http://localhost:9001  (minioadmin / minioadmin123)

# Live logs
docker compose logs -f api         # API request logs
docker compose logs -f worker      # Pipeline execution logs
docker compose logs -f scheduler   # Beat schedule logs
```

---

## Quick Reference

```
Bootstrap:      POST /bootstrap/run   → GET /bootstrap/status → GET /health/readiness
Critical tests: python -m pytest tests/unit/test_pipelines/ -v   (must be 20/20)
All tests:      python -m pytest tests/ -v                        (must be 95/95)

Category 1 params  → src/core/constants/*.py     (PR required)
Category 2 params  → .env                        (DevOps)
Category 3 params  → PATCH /config/business-rules (instant, audited)
Category 4 params  → auto via feedback_recalibration_pipeline (weekly)

APPROVE threshold: decision_score ≥ 0.70
REVIEW  threshold: decision_score 0.40–0.69
REJECT  threshold: decision_score < 0.40
All return HTTP 200 — override always allowed
```
