"""Store historical execution volume converted to USDT.

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trade_fills",
        sa.Column("quote_quantity_usdt", sa.Numeric(30, 12), nullable=True),
    )
    op.execute(
        "UPDATE trade_fills SET quote_quantity_usdt = quote_quantity "
        "FROM orders, trade_cycles, pair_configs "
        "WHERE trade_fills.order_id = orders.id "
        "AND orders.cycle_id = trade_cycles.id "
        "AND trade_cycles.pair_id = pair_configs.id "
        "AND pair_configs.quote_asset = 'USDT'"
    )


def downgrade() -> None:
    op.drop_column("trade_fills", "quote_quantity_usdt")
