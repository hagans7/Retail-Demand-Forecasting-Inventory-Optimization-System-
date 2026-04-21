# 🛒 Retail Decision Intelligence Platform

> Retail forecasting & promotion decision system — from raw sales data to actionable business recommendations.

![Python](https://img.shields.io/badge/Python-3.11.9-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white)
![LightGBM](https://img.shields.io/badge/LightGBM-4.6.0-2F9E3A?style=flat-square)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-DC382D?style=flat-square&logo=redis&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-95%20passing-brightgreen?style=flat-square)

---

## About

This platform was built in two phases: an R&D phase validating the forecasting approach through EDA, statistical diagnostics, and modeling notebooks — followed by a productionization phase turning those results into a deployable system with automated pipelines, monitoring, and an API layer.

The goal was not just to build a model, but a system a business team could actually use: forecasts that inform inventory decisions, and promo simulations that come with uncertainty estimates and audit trails.

---

## Dataset

**Source:** [Store Item Demand Forecasting — Kaggle](https://www.kaggle.com/datasets/dhrubangtalukdar/store-item-demand-forecasting-dataset/data)

Synthetic daily retail sales data covering 5 years, 50 stores, and 50 products — designed to simulate realistic store operations with seasonal demand, weekly cycles, promotion-driven uplift, and price sensitivity.

| Property | Value |
|----------|-------|
| Granularity | Daily (Store × Item × Day) |
| Stores | 50 locations |
| Items | 50 products |
| Time Range | Jan 2019 – Dec 2023 |
| Total Rows | ~4.5M transactions |

**Available columns:** `date`, `store_id`, `item_id`, `sales`, `price`, `promo`, `weekday`, `month`

---

## What It Does

| Capability | Description |
|------------|-------------|
| 📈 **Demand Forecasting** | Predict future unit sales using historical demand, pricing, promotions, and seasonality |
| 📦 **Inventory Planning** | Estimate replenishment quantities to reduce stockout and overstock risk |
| 🏷️ **Promotion Simulation** | Measure expected sales uplift and profitability before launching discounts |
| 🔁 **Monitoring & Retraining** | Evaluate forecast quality over time and trigger model improvement workflows |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI 0.115, Pydantic v2 |
| ML | LightGBM 4.6.0, NumPy <2.0 |
| Database | PostgreSQL 16, SQLAlchemy 2.0 async |
| Cache | Redis 7 (write-through, TTL=300s) |
| Object Storage | MinIO (model artifacts) |
| Task Queue | Celery 5 + Beat scheduler |
| Deployment | Docker Compose |

---

## Getting Started

**Prerequisites:** Docker Compose, Python 3.11.9

### 1. Clone & configure

```bash
git clone https://github.com/hagans7/Retail-Demand-Forecasting-Inventory-Optimization-System-.git
cd Retail-Demand-Forecasting-Inventory-Optimization-System-
cp .env.dev.example .env.dev
```

### 2. Start services

```bash
docker compose up --build -d
```

### 3. Run migrations

```bash
docker compose exec api alembic upgrade head
```

### 4. Load sales data

```bash
docker compose cp data/retail_sales.csv postgres:/tmp/retail_sales.csv
docker compose exec postgres psql -U platform_user -d retail_decision_dev \
  -c "COPY sales_transactions(date,store_id,item_id,sales,price,promo,weekday,month) \
      FROM '/tmp/retail_sales.csv' DELIMITER ',' CSV HEADER;"
```

### 5. Bootstrap (backfill features + train model)

```bash
curl -X POST http://localhost:8000/bootstrap/run \
  -H "Content-Type: application/json" \
  -d '{"reason": "Initial setup"}'
```

> ⏳ Backfill takes ~15–20 minutes. Poll for progress:
> ```bash
> curl "http://localhost:8000/bootstrap/status?task_id={id}"
> ```

### 6. Verify readiness

```bash
curl http://localhost:8000/health/readiness
```

API docs available at: **http://localhost:8000/docs**

---

## Project Structure

```
src/
├── core/           # constants, config, logging, exceptions
├── entities/       # domain objects
├── interfaces/     # abstract base classes
├── db_models/      # SQLAlchemy ORM models
├── repositories/   # persistence layer
├── services/       # business logic
├── api/routes/     # FastAPI route handlers
├── providers/      # dependency injection wiring
├── main.py
└── worker.py       # Celery app + scheduled tasks

pipelines/          # Celery task implementations
alembic/versions/   # database migrations
tests/              # unit + integration tests
```

---

## Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Critical deployment gates (CI blocks on failure)
python -m pytest tests/unit/test_pipelines/ -v
```

95 tests total — unit and integration, including critical deployment gates.
