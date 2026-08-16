"""signal_outcomes
Revision ID: 005
Revises: 004
Create Date: 2024-01-05
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("signals", sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("signals", sa.Column("outcome_correct", sa.Boolean(), nullable=True))
    op.add_column("signals", sa.Column("actual_return_pct", sa.Float(), nullable=True))

def downgrade():
    op.drop_column("signals", "actual_return_pct")
    op.drop_column("signals", "outcome_correct")
    op.drop_column("signals", "resolved")
