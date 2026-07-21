from dataclasses import dataclass
from decimal import Decimal

from app.models import OrderSide


@dataclass(frozen=True)
class AccountedFill:
    side: OrderSide
    quantity: Decimal
    quote_quantity: Decimal
    commission_quote: Decimal


@dataclass(frozen=True)
class ProfitResult:
    gross_profit: Decimal
    commission: Decimal
    net_profit: Decimal
    base_delta: Decimal


def calculate_profit(fills: list[AccountedFill], mark_price: Decimal) -> ProfitResult:
    """Mark-to-market cycle P&L in the pair's quote asset."""
    quote_cashflow = Decimal("0")
    base_delta = Decimal("0")
    commission = Decimal("0")
    for fill in fills:
        if fill.side == OrderSide.BUY:
            quote_cashflow -= fill.quote_quantity
            base_delta += fill.quantity
        else:
            quote_cashflow += fill.quote_quantity
            base_delta -= fill.quantity
        commission += fill.commission_quote
    gross = quote_cashflow + base_delta * mark_price
    return ProfitResult(gross, commission, gross - commission, base_delta)

