# Retail Decision Intelligence Platform

A production-grade retail forecasting and promotion decision system built on LightGBM, FastAPI, PostgreSQL, and Celery. The platform covers two layers: demand forecasting engine and a decision intelligence layer that translates forecasts into promo recommendations.

---

## Background

This project started as an R&D exercise on a 5-store, 50-item retail dataset (4.5M daily transactions, 2019–2023). After validating the forecasting approach through EDA, statistical diagnostics, and modeling notebooks, the results were productionized into a deployable platform with automated pipelines, monitoring, and an API layer.

The goal was not just to build a model, but to build a system that a business team could actually use — where forecasts inform inventory decisions and promo simulations come with uncertainty estimates and audit trails.

---

## link dataset:
https://www.kaggle.com/datasets/dhrubangtalukdar/store-item-demand-forecasting-dataset/data

---
## Tech Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI 0.115, Pydantic v2 |
| ML | LightGBM 4.6.0, numpy <2.0 (compatibility constraint) |
| Database | PostgreSQL 16, SQLAlchemy 2.0 async |
| Cache | Redis 7 (write-through config cache, TTL=300s) |
| Object storage | MinIO (model artifacts) |
| Task queue | Celery 5 + Beat scheduler |
| Deployment | Docker Compose |

---

## Getting Started

**Prerequisites:** Docker Compose, Python 3.11.9

```bash
# 1. Clone and set up environment
git clone https://github.com/hagans7/Retail-Demand-Forecasting-Inventory-Optimization-System-.git
cd Retail-Demand-Forecasting-Inventory-Optimization-System-
cp .env.dev.example .env.dev

# 2. Start services
docker compose up --build -d

# 3. Run migrations
docker compose exec api alembic upgrade head

# 4. Load sales data
docker compose cp data/retail_sales.csv postgres:/tmp/retail_sales.csv
docker compose exec postgres psql -U platform_user -d retail_decision_dev \
  -c "COPY sales_transactions(date,store_id,item_id,sales,price,promo,weekday,month) \
      FROM '/tmp/retail_sales.csv' DELIMITER ',' CSV HEADER;"

# 5. Bootstrap (backfill features + train model)
curl -X POST http://localhost:8000/bootstrap/run \
  -H "Content-Type: application/json" \
  -d '{"reason": "Initial setup"}'

# Backfill takes ~15-20 minutes. Poll for progress:
curl "http://localhost:8000/bootstrap/status?task_id={id}"

# 6. Check readiness
curl http://localhost:8000/health/readiness
```

Interactive API docs: http://localhost:8000/docs

---

## Project Structure

```
src/
├── core/           constants, config, logging, exceptions
├── entities/       domain objects 
├── interfaces/     abstract base classes 
├── db_models/      SQLAlchemy ORM models
├── repositories/   persistence layer 
├── services/       business logic
├── api/routes/     FastAPI route handlers
├── providers/      dependency injection wiring
├── main.py
└── worker.py       Celery app + scheduled tasks

pipelines/          Celery task implementations
alembic/versions/   database migrations
tests/              tests (unit + integration)
```

---
## Tests

```bash
python -m pytest tests/ -v
# 95 tests — includes critical deployment gates

# Critical gates (deploy blocked if any fail):
python -m pytest tests/unit/test_pipelines/ -v
```

