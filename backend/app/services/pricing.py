from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN


HUNDRED = Decimal("100")


@dataclass(frozen=True)
class Prices:
    buy: Decimal
    sell: Decimal


def quantize(value: Decimal, precision: int, rounding: str) -> Decimal:
    step = Decimal(1).scaleb(-precision)
    return value.quantize(step, rounding=rounding)


def target_prices(
    bid: Decimal,
    ask: Decimal,
    spread_pct: Decimal,
    offset_pct: Decimal,
    irb: int,
    precision: int,
) -> Prices:
    if bid <= 0 or ask <= bid:
        raise ValueError("invalid book ticker")
    half = spread_pct / Decimal(2)
    if irb == 0:
        buy_distance = sell_distance = half
    elif irb > 0:
        buy_distance, sell_distance = offset_pct, spread_pct - offset_pct
    else:
        buy_distance, sell_distance = spread_pct - offset_pct, offset_pct
    buy = bid * (Decimal(1) - buy_distance / HUNDRED)
    sell = ask * (Decimal(1) + sell_distance / HUNDRED)
    return Prices(
        buy=quantize(buy, precision, ROUND_DOWN),
        sell=quantize(sell, precision, ROUND_DOWN),
    )


def quantities(lot_quote: Decimal, prices: Prices, precision: int) -> tuple[Decimal, Decimal]:
    return (
        quantize(lot_quote / prices.buy, precision, ROUND_DOWN),
        quantize(lot_quote / prices.sell, precision, ROUND_DOWN),
    )


def red_line_trigger_price(side: str, fill_price: Decimal, red_line_pct: Decimal) -> Decimal:
    if side == "BUY":
        return fill_price * (Decimal(1) - red_line_pct / HUNDRED)
    if side == "SELL":
        return fill_price * (Decimal(1) + red_line_pct / HUNDRED)
    raise ValueError(f"unknown side: {side}")


def red_line_crossed(side: str, fill_price: Decimal, bid: Decimal, ask: Decimal, red_line_pct: Decimal) -> bool:
    trigger_price = red_line_trigger_price(side, fill_price, red_line_pct)
    return bid <= trigger_price if side == "BUY" else ask >= trigger_price


def irb_after_unmatched_fill(current_irb: int, filled_side: str) -> int:
    """Apply the inventory movement from a one-sided red-line cycle."""
    if filled_side == "BUY":
        return current_irb - 1
    if filled_side == "SELL":
        return current_irb + 1
    raise ValueError("filled_side must be BUY or SELL")


def balance_level(value: Decimal, trigger: Decimal, limit: Decimal) -> str:
    """Return the severity for a fixed asset balance threshold."""
    if trigger <= limit:
        raise ValueError("balance trigger must be greater than balance limit")
    if value <= limit:
        return "limit"
    if value <= trigger:
        return "trigger"
    return "ok"
