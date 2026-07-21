"""Initial market maker tables."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pair_status = sa.Enum("STOPPED", "RUNNING", "PAUSED", "LIMIT_REACHED", "ERROR", name="pairstatus")
    cycle_status = sa.Enum("OPEN", "PROFITABLE", "RED_LINE", "CANCELED", name="cyclestatus")
    order_side = sa.Enum("BUY", "SELL", name="orderside")
    order_status = sa.Enum("NEW", "PARTIALLY_FILLED", "FILLED", "CANCELED", "REJECTED", "EXPIRED", name="orderstatus")
    op.create_table("pair_configs",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("exchange", sa.String(30), nullable=False),
        sa.Column("symbol", sa.String(30), nullable=False), sa.Column("base_asset", sa.String(20), nullable=False),
        sa.Column("quote_asset", sa.String(20), nullable=False), sa.Column("lot_quote", sa.Numeric(30, 12), nullable=False),
        sa.Column("spread_pct", sa.Numeric(12, 8), nullable=False), sa.Column("balance_trigger", sa.Integer(), nullable=False),
        sa.Column("balance_limit", sa.Integer(), nullable=False), sa.Column("order_offset_pct", sa.Numeric(12, 8), nullable=False),
        sa.Column("red_line_pct", sa.Numeric(12, 8), nullable=False), sa.Column("pause_minutes", sa.Integer(), nullable=False),
        sa.Column("price_precision", sa.Integer(), nullable=False), sa.Column("quantity_precision", sa.Integer(), nullable=False),
        sa.Column("irb", sa.Integer(), nullable=False), sa.Column("status", pair_status, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False), sa.Column("paused_until", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol"))
    op.create_index("ix_pair_configs_symbol", "pair_configs", ["symbol"])
    op.create_table("trade_cycles",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("pair_id", sa.Uuid(), nullable=False),
        sa.Column("status", cycle_status, nullable=False), sa.Column("reference_bid", sa.Numeric(30, 12), nullable=False),
        sa.Column("reference_ask", sa.Numeric(30, 12), nullable=False),
        sa.Column("realized_quote", sa.Numeric(30, 12), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False), sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["pair_id"], ["pair_configs.id"]), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_trade_cycles_pair_id", "trade_cycles", ["pair_id"])
    op.create_table("events",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("pair_id", sa.Uuid()),
        sa.Column("level", sa.String(20), nullable=False), sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("message", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["pair_id"], ["pair_configs.id"]), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_events_pair_id", "events", ["pair_id"])
    op.create_index("ix_events_created_at", "events", ["created_at"])
    op.create_table("orders",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("cycle_id", sa.Uuid(), nullable=False),
        sa.Column("exchange_order_id", sa.String(100), nullable=False), sa.Column("client_order_id", sa.String(64), nullable=False),
        sa.Column("side", order_side, nullable=False), sa.Column("status", order_status, nullable=False),
        sa.Column("price", sa.Numeric(30, 12), nullable=False), sa.Column("quantity", sa.Numeric(30, 12), nullable=False),
        sa.Column("executed_quantity", sa.Numeric(30, 12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["cycle_id"], ["trade_cycles.id"]), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_order_id"), sa.UniqueConstraint("exchange_order_id"))
    op.create_index("ix_orders_cycle_id", "orders", ["cycle_id"])
    op.create_index("ix_orders_exchange_order_id", "orders", ["exchange_order_id"])


def downgrade() -> None:
    op.drop_table("orders")
    op.drop_table("events")
    op.drop_table("trade_cycles")
    op.drop_table("pair_configs")

