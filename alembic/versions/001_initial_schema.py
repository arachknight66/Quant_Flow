"""Initial schema
Revision ID: 001
Revises:
Create Date: 2024-01-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("risk_tolerance", sa.String(20), server_default="moderate"),
        sa.Column("capital_usd", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()))
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table("assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("asset_type", sa.String(20), nullable=False),
        sa.Column("exchange", sa.String(50), nullable=True),
        sa.Column("currency", sa.String(10), server_default="USD"),
        sa.Column("last_updated", sa.TIMESTAMP(timezone=True), nullable=True))
    op.create_index("ix_assets_symbol", "assets", ["symbol"], unique=True)
    op.create_table("ohlcv_data",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("interval", sa.String(10), nullable=False),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("adj_close", sa.Float(), nullable=True))
    op.create_index("ix_ohlcv_asset_interval_ts", "ohlcv_data", ["asset_id","interval","ts"])
    op.create_unique_constraint("uq_ohlcv_asset_interval_ts", "ohlcv_data", ["asset_id","interval","ts"])
    op.create_table("signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("confidence", sa.Float()), sa.Column("prob_profit", sa.Float()),
        sa.Column("kelly_fraction", sa.Float()), sa.Column("suggested_allocation", sa.Float()),
        sa.Column("expected_return_lo", sa.Float()), sa.Column("expected_return_hi", sa.Float()),
        sa.Column("var_95", sa.Float()), sa.Column("sharpe_est", sa.Float()),
        sa.Column("features_snapshot", postgresql.JSONB()), sa.Column("model_version", sa.String(50)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()))
    op.create_index("ix_signals_user_created", "signals", ["user_id","created_at"])
    op.create_index("ix_signals_asset_created", "signals", ["asset_id","created_at"])

def downgrade():
    op.drop_table("signals"); op.drop_table("ohlcv_data"); op.drop_table("assets"); op.drop_table("users")
