"""ohlcv_index
Revision ID: 003
Revises: 002
Create Date: 2024-01-03
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_index(
            "ix_ohlcv_ts_desc_1d",
            "ohlcv_data",
            [sa.text("ts DESC")],
            postgresql_where=sa.text("interval = '1d'")
        )
    else:
        op.create_index(
            "ix_ohlcv_ts_desc_1d",
            "ohlcv_data",
            ["ts"],
            sqlite_where=sa.text("interval = '1d'")
        )

def downgrade():
    op.drop_index("ix_ohlcv_ts_desc_1d", table_name="ohlcv_data")
