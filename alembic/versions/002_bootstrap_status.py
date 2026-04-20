"""002 — system_bootstrap_status table.

Adds singleton table that persists Day-0 bootstrap state across container restarts.
system_id='default' is the only row ever written.

Revision: 002
Depends on: 001
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision      = "002"
down_revision = "001"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table(
        "system_bootstrap_status",
        sa.Column("system_id",                sa.String(32),               primary_key=True),
        sa.Column("is_ready",                 sa.Boolean,                  nullable=False, server_default="false"),
        sa.Column("technical_ready",          sa.Boolean,                  nullable=False, server_default="false"),
        sa.Column("recommended_ready",        sa.Boolean,                  nullable=False, server_default="false"),
        sa.Column("last_run_at",              sa.DateTime(timezone=True),  nullable=True),
        sa.Column("last_success_step",        sa.String(64),               nullable=True),
        sa.Column("resume_from",              sa.String(64),               nullable=True),
        sa.Column("sales_row_count",          sa.Integer,                  nullable=True),
        sa.Column("feature_pairs_covered",    sa.Integer,                  nullable=True),
        sa.Column("feature_days_min",         sa.Integer,                  nullable=True),
        sa.Column("feature_days_max",         sa.Integer,                  nullable=True),
        sa.Column("production_model_version", sa.String(128),              nullable=True),
        sa.Column("model_val_mae_promo",      sa.Float,                    nullable=True),
        sa.Column("minio_bucket_exists",      sa.Boolean,                  nullable=False, server_default="false"),
        sa.Column("last_backfill_date",       sa.String(32),               nullable=True),
        sa.Column("notes",                    sa.Text,                     nullable=True),
        sa.Column("updated_at",               sa.DateTime(timezone=True),  server_default=sa.text("now()")),
    )
    # Seed the singleton row
    op.execute("""
        INSERT INTO system_bootstrap_status (system_id, is_ready, technical_ready, recommended_ready)
        VALUES ('default', false, false, false)
        ON CONFLICT (system_id) DO NOTHING;
    """)


def downgrade() -> None:
    op.drop_table("system_bootstrap_status")
