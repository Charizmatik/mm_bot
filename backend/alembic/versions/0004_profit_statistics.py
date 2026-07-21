"""Add execution fills, commissions and cycle profit fields.

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("trade_cycles", "realized_quote", new_column_name="gross_profit_quote")
    op.add_column(
        "trade_cycles",
        sa.Column("commission_quote", sa.Numeric(30, 12), server_default="0", nullable=False),
    )
    op.add_column(
        "trade_cycles",
        sa.Column("net_profit_quote", sa.Numeric(30, 12), server_default="0", nullable=False),
    )
    op.add_column("trade_cycles", sa.Column("mark_price", sa.Numeric(30, 12), nullable=True))
    op.execute("UPDATE trade_cycles SET net_profit_quote = gross_profit_quote")

    op.create_table(
        "trade_fills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("exchange_trade_id", sa.String(100), nullable=False),
        sa.Column("price", sa.Numeric(30, 12), nullable=False),
        sa.Column("quantity", sa.Numeric(30, 12), nullable=False),
        sa.Column("quote_quantity", sa.Numeric(30, 12), nullable=False),
        sa.Column("commission", sa.Numeric(30, 12), nullable=False),
        sa.Column("commission_asset", sa.String(20), nullable=False),
        sa.Column("commission_quote", sa.Numeric(30, 12), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trade_fills_order_id", "trade_fills", ["order_id"])
    op.create_index("ix_trade_fills_exchange_trade_id", "trade_fills", ["exchange_trade_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_trade_fills_exchange_trade_id", table_name="trade_fills")
    op.drop_index("ix_trade_fills_order_id", table_name="trade_fills")
    op.drop_table("trade_fills")
    op.drop_column("trade_cycles", "mark_price")
    op.drop_column("trade_cycles", "net_profit_quote")
    op.drop_column("trade_cycles", "commission_quote")
    op.alter_column("trade_cycles", "gross_profit_quote", new_column_name="realized_quote")
