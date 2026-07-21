"""Replace IRB thresholds with fixed per-asset balance thresholds.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pair_configs", sa.Column("base_balance_trigger", sa.Numeric(30, 12), nullable=True))
    op.add_column("pair_configs", sa.Column("base_balance_limit", sa.Numeric(30, 12), nullable=True))
    op.add_column("pair_configs", sa.Column("quote_balance_trigger", sa.Numeric(30, 12), nullable=True))
    op.add_column("pair_configs", sa.Column("quote_balance_limit", sa.Numeric(30, 12), nullable=True))
    op.add_column(
        "pair_configs",
        sa.Column("base_balance_alerted", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "pair_configs",
        sa.Column("quote_balance_alerted", sa.Boolean(), server_default=sa.false(), nullable=False),
    )

    # Old values represented IRB counts and cannot be converted into asset
    # units. Preserve them as non-zero placeholders while keeping all existing
    # pairs stopped so the operator can enter the correct fixed thresholds.
    op.execute(
        """
        UPDATE pair_configs
        SET base_balance_trigger = balance_limit,
            base_balance_limit = balance_trigger,
            quote_balance_trigger = balance_limit,
            quote_balance_limit = balance_trigger,
            enabled = false,
            status = 'STOPPED'
        """
    )
    for column in (
        "base_balance_trigger",
        "base_balance_limit",
        "quote_balance_trigger",
        "quote_balance_limit",
    ):
        op.alter_column("pair_configs", column, nullable=False)
    op.drop_column("pair_configs", "balance_limit")
    op.drop_column("pair_configs", "balance_trigger")


def downgrade() -> None:
    op.add_column("pair_configs", sa.Column("balance_trigger", sa.Integer(), nullable=True))
    op.add_column("pair_configs", sa.Column("balance_limit", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE pair_configs
        SET balance_trigger = GREATEST(1, CEIL(base_balance_limit)::integer),
            balance_limit = GREATEST(1, CEIL(base_balance_trigger)::integer)
        """
    )
    op.alter_column("pair_configs", "balance_trigger", nullable=False)
    op.alter_column("pair_configs", "balance_limit", nullable=False)
    op.drop_column("pair_configs", "quote_balance_alerted")
    op.drop_column("pair_configs", "base_balance_alerted")
    op.drop_column("pair_configs", "quote_balance_limit")
    op.drop_column("pair_configs", "quote_balance_trigger")
    op.drop_column("pair_configs", "base_balance_limit")
    op.drop_column("pair_configs", "base_balance_trigger")
