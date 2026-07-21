from decimal import Decimal

from app.models import OrderSide
from app.services.accounting import AccountedFill, calculate_profit


def test_successful_cycle_profit_subtracts_commissions() -> None:
    result = calculate_profit([
        AccountedFill(OrderSide.BUY, Decimal("1"), Decimal("100"), Decimal("0.10")),
        AccountedFill(OrderSide.SELL, Decimal("1"), Decimal("101"), Decimal("0.101")),
    ], Decimal("101"))
    assert result.gross_profit == Decimal("1")
    assert result.commission == Decimal("0.201")
    assert result.net_profit == Decimal("0.799")
    assert result.base_delta == Decimal("0")


def test_unequal_quantities_are_marked_to_market() -> None:
    result = calculate_profit([
        AccountedFill(OrderSide.BUY, Decimal("1"), Decimal("100"), Decimal("0")),
        AccountedFill(OrderSide.SELL, Decimal("0.99"), Decimal("99.99"), Decimal("0")),
    ], Decimal("100.5"))
    assert result.base_delta == Decimal("0.01")
    assert result.gross_profit == Decimal("0.995")


def test_red_line_buy_is_marked_at_closing_market() -> None:
    result = calculate_profit([
        AccountedFill(OrderSide.BUY, Decimal("1"), Decimal("100"), Decimal("0.1")),
    ], Decimal("99"))
    assert result.gross_profit == Decimal("-1")
    assert result.net_profit == Decimal("-1.1")
