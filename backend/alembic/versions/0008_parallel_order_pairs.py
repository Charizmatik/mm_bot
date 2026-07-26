"""Add parallel grid order-pair state.

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pair_configs",
        sa.Column("order_pair_count", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "trade_cycles",
        sa.Column("grid_slot", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "trade_cycles",
        sa.Column("retiring", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "trade_cycles",
        sa.Column("successor_spawned", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "trade_cycles",
        sa.Column("replacement_after", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trade_cycles", "replacement_after")
    op.drop_column("trade_cycles", "successor_spawned")
    op.drop_column("trade_cycles", "retiring")
    op.drop_column("trade_cycles", "grid_slot")
    op.drop_column("pair_configs", "order_pair_count")
