"""Align unique indexes with the SQLAlchemy models.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The constraints already guarantee uniqueness, so replacing them with
    # unique indexes is safe and does not rewrite or remove application data.
    op.drop_constraint("orders_exchange_order_id_key", "orders", type_="unique")
    op.drop_index("ix_orders_exchange_order_id", table_name="orders")
    op.create_index("ix_orders_exchange_order_id", "orders", ["exchange_order_id"], unique=True)

    op.drop_constraint("pair_configs_symbol_key", "pair_configs", type_="unique")
    op.drop_index("ix_pair_configs_symbol", table_name="pair_configs")
    op.create_index("ix_pair_configs_symbol", "pair_configs", ["symbol"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_pair_configs_symbol", table_name="pair_configs")
    op.create_index("ix_pair_configs_symbol", "pair_configs", ["symbol"], unique=False)
    op.create_unique_constraint("pair_configs_symbol_key", "pair_configs", ["symbol"])

    op.drop_index("ix_orders_exchange_order_id", table_name="orders")
    op.create_index("ix_orders_exchange_order_id", "orders", ["exchange_order_id"], unique=False)
    op.create_unique_constraint("orders_exchange_order_id_key", "orders", ["exchange_order_id"])

