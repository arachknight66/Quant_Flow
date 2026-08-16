"""alert subscriptions
Revision ID: 007
Revises: 006
Create Date: 2024-01-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True)

    op.create_table("alert_subscriptions",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", uuid_type, sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.sql.true()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now())
    )
    op.create_index("ix_alert_subscriptions_user_id", "alert_subscriptions", ["user_id"])
    op.create_unique_constraint("uq_alert_subscriptions_user_asset", "alert_subscriptions", ["user_id", "asset_id"])

def downgrade():
    op.drop_table("alert_subscriptions")
