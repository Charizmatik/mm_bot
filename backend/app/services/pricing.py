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
    precision: int,
) -> Prices:
    if bid <= 0 or ask <= bid:
        raise ValueError("invalid book ticker")
    half = spread_pct / Decimal(2)
    buy = bid * (Decimal(1) - half / HUNDRED)
    sell = ask * (Decimal(1) + half / HUNDRED)
    return Prices(
        buy=quantize(buy, precision, ROUND_DOWN),
        sell=quantize(sell, precision, ROUND_DOWN),
    )


def adjacent_prices(
    filled_side: str,
    fill_price: Decimal,
    spread_pct: Decimal,
    gap_pct: Decimal,
    precision: int,
) -> Prices:
    """Build the next grid cell directly beside a filled outer order."""
    tick = Decimal(1).scaleb(-precision)
    if filled_side == "SELL":
        buy = quantize(fill_price * (Decimal(1) + gap_pct / HUNDRED), precision, ROUND_DOWN)
        if buy <= fill_price:
            buy = quantize(fill_price, precision, ROUND_DOWN) + tick
        sell = quantize(buy * (Decimal(1) + spread_pct / HUNDRED), precision, ROUND_DOWN)
        return Prices(buy=buy, sell=sell)
    if filled_side == "BUY":
        sell = quantize(fill_price * (Decimal(1) - gap_pct / HUNDRED), precision, ROUND_DOWN)
        if sell >= fill_price:
            sell = quantize(fill_price, precision, ROUND_DOWN) - tick
        buy = quantize(sell * (Decimal(1) - spread_pct / HUNDRED), precision, ROUND_DOWN)
        return Prices(buy=buy, sell=sell)
    raise ValueError("filled_side must be BUY or SELL")


def prices_are_marketable(prices: Prices, bid: Decimal, ask: Decimal) -> bool:
    return prices.buy >= ask or prices.sell <= bid


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


def balance_level(value: Decimal, trigger: Decimal, limit: Decimal) -> str:
    """Return the severity for a fixed asset balance threshold."""
    if trigger <= limit:
        raise ValueError("balance trigger must be greater than balance limit")
    if value <= limit:
        return "limit"
    if value <= trigger:
        return "trigger"
    return "ok"
