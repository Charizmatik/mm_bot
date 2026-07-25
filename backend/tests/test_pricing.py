from decimal import Decimal

import pytest

from app.services.pricing import (
    Prices, balance_level, irb_after_unmatched_fill, quantities, red_line_crossed,
    red_line_trigger_price, target_prices,
)


def test_neutral_prices_match_spec_example() -> None:
    result = target_prices(Decimal("60000"), Decimal("60001"), Decimal("0.15"), Decimal("0.005"), 0, 0)
    assert result == Prices(buy=Decimal("59955"), sell=Decimal("60046"))


def test_positive_irb_moves_buy_near_and_sell_far() -> None:
    result = target_prices(Decimal("60000"), Decimal("60001"), Decimal("0.15"), Decimal("0.005"), 2, 0)
    assert result.buy == Decimal("59997")
    assert result.sell == Decimal("60088")


def test_negative_irb_reverses_skew() -> None:
    result = target_prices(Decimal("60000"), Decimal("60001"), Decimal("0.15"), Decimal("0.005"), -1, 0)
    assert result.buy == Decimal("59913")
    assert result.sell == Decimal("60004")


def test_quantities_are_quote_lots() -> None:
    buy, sell = quantities(Decimal("100"), Prices(Decimal("50"), Decimal("100")), 4)
    assert buy == Decimal("2.0000")
    assert sell == Decimal("1.0000")


def test_red_line_direction() -> None:
    assert red_line_crossed("BUY", Decimal("100"), Decimal("98.9"), Decimal("99"), Decimal("1"))
    assert red_line_crossed("SELL", Decimal("100"), Decimal("101"), Decimal("101.1"), Decimal("1"))
    assert not red_line_crossed("BUY", Decimal("100"), Decimal("99.5"), Decimal("100"), Decimal("1"))


def test_red_line_trigger_price() -> None:
    assert red_line_trigger_price("BUY", Decimal("100"), Decimal("1")) == Decimal("99")
    assert red_line_trigger_price("SELL", Decimal("100"), Decimal("1")) == Decimal("101")
    with pytest.raises(ValueError):
        red_line_trigger_price("UNKNOWN", Decimal("100"), Decimal("1"))


def test_irb_tracks_one_sided_red_line_cycles() -> None:
    assert irb_after_unmatched_fill(0, "SELL") == 1
    assert irb_after_unmatched_fill(1, "SELL") == 2
    assert irb_after_unmatched_fill(0, "BUY") == -1
    assert irb_after_unmatched_fill(-1, "BUY") == -2


def test_irb_rejects_unknown_side() -> None:
    with pytest.raises(ValueError):
        irb_after_unmatched_fill(0, "UNKNOWN")


def test_fixed_balance_levels() -> None:
    assert balance_level(Decimal("0.02"), Decimal("0.01"), Decimal("0.005")) == "ok"
    assert balance_level(Decimal("0.01"), Decimal("0.01"), Decimal("0.005")) == "trigger"
    assert balance_level(Decimal("0.005"), Decimal("0.01"), Decimal("0.005")) == "limit"


def test_balance_trigger_must_be_above_limit() -> None:
    with pytest.raises(ValueError):
        balance_level(Decimal("10"), Decimal("5"), Decimal("5"))
