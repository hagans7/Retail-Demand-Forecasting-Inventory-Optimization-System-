"""001 — Initial schema + item_financial_assumptions __default__ seed.

Revision: 001
Creates all tables and seeds the mandatory __default__ COGS sentinel row.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # sales_transactions
    op.create_table(
        "sales_transactions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("store_id", sa.String(50), nullable=False),
        sa.Column("item_id",  sa.String(50), nullable=False),
        sa.Column("date",     sa.Date, nullable=False),
        sa.Column("sales",    sa.Integer, nullable=False),
        sa.Column("price",    sa.Float, nullable=False),
        sa.Column("promo",    sa.Integer, nullable=False, default=0),
        sa.Column("weekday",  sa.Integer, nullable=True),
        sa.Column("month",    sa.Integer, nullable=True),
    )
    op.create_index("idx_sales_date_pair", "sales_transactions", ["date", "store_id", "item_id"])
    op.create_unique_constraint("uq_sales_txn", "sales_transactions", ["store_id", "item_id", "date"])

    # model_registry
    op.create_table(
        "model_registry",
        sa.Column("version_id",         sa.String(128), primary_key=True),
        sa.Column("version_tag",         sa.String(64),  nullable=False),
        sa.Column("quantile_level",      sa.Float,       nullable=False),
        sa.Column("algorithm",           sa.String(64),  nullable=False),
        sa.Column("features",            JSONB,          nullable=False),
        sa.Column("target",              sa.String(32),  nullable=False),
        sa.Column("loss",                sa.String(64),  nullable=False),
        sa.Column("best_iteration",      sa.Integer,     nullable=False),
        sa.Column("trained_on_date",     sa.DateTime(timezone=True)),
        sa.Column("val_mae",             sa.Float,       nullable=False),
        sa.Column("val_mae_promo",       sa.Float,       nullable=False),
        sa.Column("val_uf_promo_pct",    sa.Float,       nullable=False),
        sa.Column("naive_mae",           sa.Float,       nullable=False),
        sa.Column("artifact_path",       sa.String(512), nullable=True),
        sa.Column("training_data_start", sa.Date,        nullable=True),
        sa.Column("training_data_end",   sa.Date,        nullable=True),
        sa.Column("training_data_rows",  sa.Integer,     nullable=False, server_default="0"),
        sa.Column("training_seconds",    sa.Float,       nullable=False, server_default="0"),
        sa.Column("training_data_hash",  sa.String(64),  nullable=True),
        sa.Column("is_production",       sa.Boolean,     nullable=False, server_default="false"),
        sa.Column("promoted_at",         sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived",            sa.Boolean,     nullable=False, server_default="false"),
        sa.Column("archived_at",         sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at",          sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_registry_production", "model_registry", ["is_production", "quantile_level", "created_at"])

    # feature_snapshots
    op.create_table(
        "feature_snapshots",
        sa.Column("id",            sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("store_id",      sa.String(50), nullable=False),
        sa.Column("item_id",       sa.String(50), nullable=False),
        sa.Column("snapshot_date", sa.Date,       nullable=False),
        sa.Column("lag_7",         sa.Float, nullable=True),
        sa.Column("lag_14",        sa.Float, nullable=True),
        sa.Column("lag_21",        sa.Float, nullable=True),
        sa.Column("rolling_mean_7",  sa.Float, nullable=True),
        sa.Column("rolling_mean_14", sa.Float, nullable=True),
        sa.Column("rolling_mean_28", sa.Float, nullable=True),
        sa.Column("rolling_std_7",   sa.Float, nullable=True),
        sa.Column("rolling_std_14",  sa.Float, nullable=True),
        sa.Column("rolling_cv_7",    sa.Float, nullable=True),
        sa.Column("rolling_cv_14",   sa.Float, nullable=True),
        sa.Column("wd_0",  sa.Integer, nullable=True),
        sa.Column("wd_1",  sa.Integer, nullable=True),
        sa.Column("wd_2",  sa.Integer, nullable=True),
        sa.Column("wd_3",  sa.Integer, nullable=True),
        sa.Column("wd_4",  sa.Integer, nullable=True),
        sa.Column("wd_5",  sa.Integer, nullable=True),
        sa.Column("wd_6",  sa.Integer, nullable=True),
        sa.Column("month_sin", sa.Float, nullable=True),
        sa.Column("month_cos", sa.Float, nullable=True),
        sa.Column("doy_sin",   sa.Float, nullable=True),
        sa.Column("doy_cos",   sa.Float, nullable=True),
        sa.Column("week_of_month", sa.Integer, nullable=True),
        sa.Column("promo",              sa.Integer, nullable=True),
        sa.Column("promo_streak_day",   sa.Integer, nullable=True),
        sa.Column("days_since_last_promo", sa.Float, nullable=True),
        sa.Column("history_days", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at",   sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_snapshot_date_pair", "feature_snapshots", ["snapshot_date", "store_id", "item_id"])
    op.create_unique_constraint("uq_feature_snapshot_pair_date", "feature_snapshots",
                                ["store_id", "item_id", "snapshot_date"])

    # forecast_results
    op.create_table(
        "forecast_results",
        sa.Column("forecast_id",      sa.String(64),  primary_key=True),
        sa.Column("store_id",         sa.String(50),  nullable=False),
        sa.Column("item_id",          sa.String(50),  nullable=False),
        sa.Column("forecast_date",    sa.Date,        nullable=False),
        sa.Column("predicted_sales",  sa.Float,       nullable=False),
        sa.Column("lower_bound",      sa.Float,       nullable=False),
        sa.Column("upper_bound",      sa.Float,       nullable=False),
        sa.Column("revenue_estimate", sa.Float,       nullable=True),
        sa.Column("feature_snapshot", JSONB,          nullable=True),
        sa.Column("model_version",    sa.String(100), nullable=False),
        sa.Column("quantile_level",   sa.Float,       nullable=False, server_default="0.6"),
        sa.Column("restock_qty",      sa.Integer,     nullable=True),
        sa.Column("stockout_risk",    sa.String(20),  nullable=True),
        sa.Column("safety_factor",    sa.Float,       nullable=True),
        sa.Column("reason_codes",     JSONB,          nullable=True),
        sa.Column("cold_start_tier",  sa.String(20),  nullable=False, server_default="'NONE'"),
        sa.Column("generated_at",     sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_forecast_date_pair", "forecast_results", ["forecast_date", "store_id", "item_id"])

    # business_configs
    op.create_table(
        "business_configs",
        sa.Column("config_key",     sa.String(100),              primary_key=True),
        sa.Column("config_value",   JSONB,                       nullable=False),
        sa.Column("config_type",    sa.String(20),               nullable=False),
        sa.Column("updated_by",     sa.String(100),              nullable=False),
        sa.Column("updated_at",     sa.DateTime(timezone=True),  server_default=sa.text("now()")),
        sa.Column("reason",         sa.Text,                     nullable=False),
        sa.Column("previous_value", JSONB,                       nullable=True),
    )

    # monitoring_metrics
    op.create_table(
        "monitoring_metrics",
        sa.Column("metric_id",       sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("metric_name",     sa.String(100), nullable=False),
        sa.Column("metric_value",    sa.Float,       nullable=False),
        sa.Column("segment",         sa.String(50),  nullable=True),
        sa.Column("computed_at",     sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_version",   sa.String(128), nullable=True),
        sa.Column("rolling_7d_value",  sa.Float, nullable=True),
        sa.Column("rolling_28d_value", sa.Float, nullable=True),
    )
    op.create_index("idx_monitoring_name_time", "monitoring_metrics", ["metric_name", "computed_at"])

    # analytics_snapshots
    op.create_table(
        "analytics_snapshots",
        sa.Column("snapshot_id",        sa.String(64), primary_key=True),
        sa.Column("period_start",        sa.Date,      nullable=False),
        sa.Column("period_end",          sa.Date,      nullable=False),
        sa.Column("metrics",             JSONB,        nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("revenue_metrics",     JSONB,        nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("promo_effectiveness", JSONB,        nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("computed_at",         sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # hypothesis_results
    op.create_table(
        "hypothesis_results",
        sa.Column("result_id",       sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("hypothesis_id",   sa.String(50), nullable=False),
        sa.Column("current_value",   sa.Float, nullable=False),
        sa.Column("baseline_value",  sa.Float, nullable=False),
        sa.Column("deviation_pct",   sa.Float, nullable=False),
        sa.Column("status",          sa.String(30), nullable=False),
        sa.Column("period_start",    sa.Date, nullable=False),
        sa.Column("period_end",      sa.Date, nullable=False),
        sa.Column("sample_size",     sa.Integer, nullable=False),
        sa.Column("alert_triggered", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("computed_at",     sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # drift_metrics
    op.create_table(
        "drift_metrics",
        sa.Column("metric_id",     sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("feature_name",  sa.String(60), nullable=False),
        sa.Column("psi_score",     sa.Float, nullable=True),
        sa.Column("shift_pct",     sa.Float, nullable=True),
        sa.Column("severity",      sa.String(20), nullable=False),
        sa.Column("current_mean",  sa.Float, nullable=False),
        sa.Column("training_mean", sa.Float, nullable=False),
        sa.Column("current_std",   sa.Float, nullable=False),
        sa.Column("training_std",  sa.Float, nullable=False),
        sa.Column("computed_at",   sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # override_events
    op.create_table(
        "override_events",
        sa.Column("event_id",              sa.String(64), primary_key=True),
        sa.Column("store_id",              sa.String(50), nullable=False),
        sa.Column("item_id",               sa.String(50), nullable=False),
        sa.Column("override_type",         sa.String(30), nullable=False),
        sa.Column("system_recommendation", JSONB, nullable=False),
        sa.Column("human_override",        JSONB, nullable=False),
        sa.Column("override_reason",       sa.Text, nullable=False),
        sa.Column("user_id",               sa.String(100), nullable=False),
        sa.Column("created_at",            sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("outcome",               sa.String(100), nullable=True),
    )

    # data_quality_events
    op.create_table(
        "data_quality_events",
        sa.Column("event_id",            sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("run_date",            sa.Date, nullable=False),
        sa.Column("checks",              JSONB, nullable=False),
        sa.Column("all_critical_passed", sa.Boolean, nullable=False),
        sa.Column("pipeline_blocked",    sa.Boolean, nullable=False),
        sa.Column("fallback_strategy",   sa.String(30), nullable=False, server_default="'NONE'"),
        sa.Column("created_at",          sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # ================================================================
    # V2 Decision Intelligence Tables
    # ================================================================

    # item_financial_assumptions
    op.create_table(
        "item_financial_assumptions",
        sa.Column("item_id",              sa.String(50), primary_key=True),
        sa.Column("cogs_pct",             sa.Float, nullable=False),
        sa.Column("promo_fixed_cost",     sa.Float, nullable=False, server_default="0.0"),
        sa.Column("holding_cost_per_day", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("updated_by",           sa.String(100), nullable=True),
        sa.Column("updated_at",           sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("notes",                sa.Text, nullable=True),
    )

    # ── CRITICAL SEED: __default__ sentinel row ──────────────────────
    op.execute("""
        INSERT INTO item_financial_assumptions
            (item_id, cogs_pct, promo_fixed_cost, holding_cost_per_day, notes)
        VALUES
            ('__default__', 0.60, 100.0, 0.015,
             'Default NORMAL_MARGIN scenario. Replace with item-specific values for accuracy.')
        ON CONFLICT (item_id) DO NOTHING;
    """)

    # item_elasticity_observed
    op.create_table(
        "item_elasticity_observed",
        sa.Column("item_id",             sa.String(50), nullable=False),
        sa.Column("store_id",            sa.String(50), nullable=False),
        sa.Column("elasticity_initial",  sa.Float, nullable=False),
        sa.Column("elasticity_observed", sa.Float, nullable=False),
        sa.Column("n_observations",      sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_calibrated_at",  sa.DateTime(timezone=True), nullable=True),
        sa.Column("accuracy_score",      sa.Float, nullable=True),
        sa.Column("source",              sa.String(30), nullable=False, server_default="'initial_estimate'"),
    )
    op.create_primary_key("pk_elasticity", "item_elasticity_observed", ["item_id", "store_id"])
    op.create_index("idx_elasticity_last_cal", "item_elasticity_observed", ["last_calibrated_at"])

    # decision_simulations
    op.create_table(
        "decision_simulations",
        sa.Column("simulation_id",        sa.String(64), primary_key=True),
        sa.Column("store_id",             sa.String(50), nullable=False),
        sa.Column("item_id",              sa.String(50), nullable=False),
        sa.Column("recommendation",       sa.String(10), nullable=False),
        sa.Column("decision_score",       sa.Float, nullable=False),
        sa.Column("predicted_roi",        sa.Float, nullable=True),
        sa.Column("probability_profitable", sa.Float, nullable=True),
        sa.Column("uncertainty_band",     JSONB, nullable=True),
        sa.Column("risk_notes",           JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("recommended_action",   sa.Text, nullable=True),
        sa.Column("config_snapshot",      JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("predicted_uplift_pct", sa.Float, nullable=True),
        sa.Column("promo_discount_pct",   sa.Float, nullable=True),
        sa.Column("status",               sa.String(30), nullable=False, server_default=sa.text("'PENDING'::string")),
        sa.Column("actual_outcome",       JSONB, nullable=True),
        sa.Column("override_flag",        sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at",           sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("resolved_at",          sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_decision_status_time", "decision_simulations", ["status", "created_at"])
    op.create_index("idx_decision_pair_time",   "decision_simulations", ["store_id", "item_id", "created_at"])
    op.create_index("idx_decision_created_desc","decision_simulations", ["created_at"])


def downgrade() -> None:
    op.drop_table("decision_simulations")
    op.drop_table("item_elasticity_observed")
    op.drop_table("item_financial_assumptions")
    op.drop_table("data_quality_events")
    op.drop_table("override_events")
    op.drop_table("drift_metrics")
    op.drop_table("hypothesis_results")
    op.drop_table("analytics_snapshots")
    op.drop_table("monitoring_metrics")
    op.drop_table("business_configs")
    op.drop_table("forecast_results")
    op.drop_table("feature_snapshots")
    op.drop_table("model_registry")
    op.drop_table("sales_transactions")
