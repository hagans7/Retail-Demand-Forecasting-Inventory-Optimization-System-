# Retail Decision Intelligence Platform

A production-grade retail forecasting and promotion decision system built on LightGBM, FastAPI, PostgreSQL, and Celery. The platform covers two layers: demand forecasting engine and a decision intelligence layer that translates forecasts into promo recommendations.

---

## Background

This project started as an R&D exercise on a 5-store, 50-item retail dataset (4.5M daily transactions, 2019–2023). After validating the forecasting approach through EDA, statistical diagnostics, and modeling notebooks, the results were productionized into a deployable platform with automated pipelines, monitoring, and an API layer.

The goal was not just to build a model, but to build a system that a business team could actually use — where forecasts inform inventory decisions and promo simulations come with uncertainty estimates and audit trails.

---
# Dataset

This project uses the **Store Item Demand Forecasting Dataset** from Kaggle.

Source: [Store Item Demand Forecasting Dataset](https://www.kaggle.com/datasets/dhrubangtalukdar/store-item-demand-forecasting-dataset/data) 

---

## Overview

The dataset contains synthetic daily retail sales data designed to simulate realistic store operations.

It is structured for forecasting, inventory planning, promotion analysis, and retail machine learning use cases.

The data covers **January 2019 to December 2023** and represents demand behavior across multiple stores and products.

---

## Core Characteristics

- **Granularity:** Daily transactions  
- **Stores:** 50 locations  
- **Items:** 50 products  
- **Time Range:** 5 years  
- **Observation Level:** Store × Item × Day  

This results in millions of time-series observations suitable for production-style experimentation.

---

## Available Columns

| Column | Description |
|---|---|
| `date` | Observation date |
| `store_id` | Unique store identifier |
| `item_id` | Unique product identifier |
| `sales` | Units sold on that day |
| `price` | Selling price |
| `promo` | Promotion flag (1 = active) |
| `weekday` | Day of week |
| `month` | Month number |

---

## Why This Dataset Was Chosen

This dataset was selected because it captures several important retail demand behaviors:

- Multi-store and multi-product forecasting challenges  
- Seasonal demand fluctuations  
- Weekly sales cycles  
- Promotion-driven uplift  
- Price sensitivity behavior  
- Long-term growth trend  
- Random noise similar to real operations  

These properties make it highly relevant for building forecasting and decision-support systems.

---

## Use in This Project

The dataset is used as the foundation for:

### Demand Forecasting

Predict future unit sales using historical demand, pricing, promotions, and seasonality.

### Inventory Planning

Estimate replenishment quantities to reduce stockout and overstock risk.

### Promotion Simulation

Measure expected sales uplift and profitability before launching discounts.

### Monitoring & Retraining

Evaluate forecast quality over time and trigger model improvement workflows.

---

## Important Note

This dataset is **synthetic**, meaning it was artificially generated to mimic realistic retail patterns.

It does not contain real customer or company data, making it safe for experimentation and portfolio projects.

---

## Scale Advantage

Because the dataset spans multiple years and many store-item combinations, it enables testing of:

- Large-scale batch forecasting  
- Automated pipelines  
- Backtesting frameworks  
- Multi-entity time-series modeling  
- Production-style MLOps workflows  

---

## Summary

This dataset provides a practical environment to build an end-to-end retail forecasting platform using realistic business scenarios without relying on private commercial data.

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

