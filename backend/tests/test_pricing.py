from decimal import Decimal

import pytest

from app.services.pricing import (
    Prices, adjacent_prices, balance_level, prices_are_marketable, quantities,
    red_line_crossed, red_line_trigger_price, target_prices,
)


def test_neutral_prices_match_spec_example() -> None:
    result = target_prices(Decimal("60000"), Decimal("60001"), Decimal("0.15"), 0)
    assert result == Prices(buy=Decimal("59955"), sell=Decimal("60046"))


def test_upper_grid_cell_is_adjacent_without_overlap() -> None:
    result = adjacent_prices("SELL", Decimal("100"), Decimal("0.15"), Decimal("0.001"), 3)
    assert result == Prices(buy=Decimal("100.001"), sell=Decimal("100.151"))


def test_lower_grid_cell_is_adjacent_without_overlap() -> None:
    result = adjacent_prices("BUY", Decimal("100"), Decimal("0.15"), Decimal("0.001"), 3)
    assert result == Prices(buy=Decimal("99.849"), sell=Decimal("99.999"))


def test_adjacent_price_uses_at_least_one_tick_when_gap_rounds_away() -> None:
    result = adjacent_prices("SELL", Decimal("100"), Decimal("0.15"), Decimal("0.001"), 2)
    assert result.buy == Decimal("100.01")


def test_marketable_grid_cell_is_detected() -> None:
    assert prices_are_marketable(Prices(Decimal("101"), Decimal("102")), Decimal("100"), Decimal("101"))
    assert prices_are_marketable(Prices(Decimal("99"), Decimal("100")), Decimal("100"), Decimal("101"))
    assert not prices_are_marketable(Prices(Decimal("99"), Decimal("102")), Decimal("100"), Decimal("101"))


def test_order_pair_quantities_are_identical_and_do_not_exceed_quote_lot() -> None:
    buy, sell = quantities(Decimal("100"), Prices(Decimal("50"), Decimal("100")), 4)
    assert buy == Decimal("1.0000")
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


def test_fixed_balance_levels() -> None:
    assert balance_level(Decimal("0.02"), Decimal("0.01"), Decimal("0.005")) == "ok"
    assert balance_level(Decimal("0.01"), Decimal("0.01"), Decimal("0.005")) == "trigger"
    assert balance_level(Decimal("0.005"), Decimal("0.01"), Decimal("0.005")) == "limit"


def test_balance_trigger_must_be_above_limit() -> None:
    with pytest.raises(ValueError):
        balance_level(Decimal("10"), Decimal("5"), Decimal("5"))
