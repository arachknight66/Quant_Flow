"""watchlist
Revision ID: 006
Revises: 005
Create Date: 2024-01-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True)

    op.create_table("watchlist_items",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("user_id", uuid_type, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", uuid_type, sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("added_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("notes", sa.Text(), nullable=True)
    )
    op.create_index("ix_watchlist_items_user_id", "watchlist_items", ["user_id"])
    op.create_unique_constraint("uq_watchlist_user_asset", "watchlist_items", ["user_id", "asset_id"])

def downgrade():
    op.drop_table("watchlist_items")
