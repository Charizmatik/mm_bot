"""Remove pair-level paper-profit setting.

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("pair_configs", "paper_profit")


def downgrade() -> None:
    op.add_column(
        "pair_configs",
        sa.Column("paper_profit", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
