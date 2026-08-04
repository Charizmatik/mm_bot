"""Store daily account equity snapshots.

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_equity_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("equity_usdt", sa.Numeric(30, 12), nullable=False),
        sa.Column("priced_assets", sa.Integer(), nullable=False),
        sa.Column("unpriced_assets", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_date"),
    )
    op.create_index(
        "ix_account_equity_snapshots_snapshot_date",
        "account_equity_snapshots",
        ["snapshot_date"],
    )
    op.create_table(
        "account_asset_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("asset", sa.String(length=20), nullable=False),
        sa.Column("free", sa.Numeric(30, 12), nullable=False),
        sa.Column("locked", sa.Numeric(30, 12), nullable=False),
        sa.Column("total", sa.Numeric(30, 12), nullable=False),
        sa.Column("price_usdt", sa.Numeric(30, 12), nullable=True),
        sa.Column("value_usdt", sa.Numeric(30, 12), nullable=True),
        sa.Column("valuation_source", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(["snapshot_id"], ["account_equity_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_account_asset_snapshots_snapshot_id",
        "account_asset_snapshots",
        ["snapshot_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_account_asset_snapshots_snapshot_id", table_name="account_asset_snapshots")
    op.drop_table("account_asset_snapshots")
    op.drop_index(
        "ix_account_equity_snapshots_snapshot_date",
        table_name="account_equity_snapshots",
    )
    op.drop_table("account_equity_snapshots")
