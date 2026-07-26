from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN


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


def closest_maker_adjacent_prices(
    filled_side: str,
    fill_price: Decimal,
    bid: Decimal,
    ask: Decimal,
    spread_pct: Decimal,
    gap_pct: Decimal,
    precision: int,
) -> Prices | None:
    """Keep an adjacent cell as close as possible while both orders remain makers."""
    prices = adjacent_prices(filled_side, fill_price, spread_pct, gap_pct, precision)
    if not prices_are_marketable(prices, bid, ask):
        return prices

    tick = Decimal(1).scaleb(-precision)
    if filled_side == "SELL":
        # The market moved above the desired cell. Lift only as much as
        # necessary for its SELL to sit one tick above the current bid.
        if prices.buy >= ask:
            return None
        factor = Decimal(1) + spread_pct / HUNDRED
        buy = max(
            prices.buy,
            quantize((bid + tick) / factor, precision, ROUND_CEILING),
        )
        sell = quantize(buy * factor, precision, ROUND_DOWN)
        while sell <= bid:
            buy += tick
            sell = quantize(buy * factor, precision, ROUND_DOWN)
        if buy >= ask:
            return None
        return Prices(buy=buy, sell=sell)

    if filled_side == "BUY":
        # The market moved below the desired cell. Lower only as much as
        # necessary for its BUY to sit one tick below the current ask.
        if prices.sell <= bid:
            return None
        factor = Decimal(1) - spread_pct / HUNDRED
        max_buy = quantize(ask, precision, ROUND_CEILING) - tick
        sell = min(
            prices.sell,
            quantize((max_buy + tick) / factor, precision, ROUND_CEILING) - tick,
        )
        buy = quantize(sell * factor, precision, ROUND_DOWN)
        while buy >= ask:
            sell -= tick
            buy = quantize(sell * factor, precision, ROUND_DOWN)
        if sell <= bid:
            return None
        return Prices(buy=buy, sell=sell)

    raise ValueError("filled_side must be BUY or SELL")


def prices_are_marketable(prices: Prices, bid: Decimal, ask: Decimal) -> bool:
    return prices.buy >= ask or prices.sell <= bid


def quantities(lot_quote: Decimal, prices: Prices, precision: int) -> tuple[Decimal, Decimal]:
    # Both sides of one pair must trade exactly the same base quantity.
    # Derive it from the more expensive side so neither order exceeds the
    # configured quote-asset lot after rounding.
    quantity = quantize(lot_quote / max(prices.buy, prices.sell), precision, ROUND_DOWN)
    return quantity, quantity


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


def estimated_balance_threshold_price(
    *,
    side: str,
    market_price: Decimal,
    balance: Decimal,
    threshold: Decimal,
    lot_quote: Decimal,
    order_pair_count: int,
    spread_pct: Decimal,
    red_line_pct: Decimal,
) -> Decimal | None:
    """Estimate the market price where adverse cycles consume a balance threshold.

    A rising market consumes base inventory through SELL cycles; a falling
    market consumes quote inventory through BUY cycles. Parallel order pairs
    are treated as one wave, and every next wave starts after the configured
    spread and red-line move. This is intentionally a scenario estimate, not
    an exchange guarantee.
    """
    if market_price <= 0 or balance < 0 or threshold < 0 or lot_quote <= 0:
        return None
    if balance <= threshold:
        return market_price

    pairs = max(order_pair_count, 1)
    half_spread = spread_pct / (HUNDRED * Decimal("2"))
    red_line = red_line_pct / HUNDRED

    if side == "BUY":
        buy_factor = Decimal("1") - half_spread
        sell_factor = Decimal("1") + half_spread
        step_factor = buy_factor * (Decimal("1") - red_line)
        quote_per_order = lot_quote * buy_factor / sell_factor
        if step_factor <= 0 or quote_per_order <= 0:
            return None
        orders = int(
            ((balance - threshold) / quote_per_order).to_integral_value(
                rounding=ROUND_CEILING
            )
        )
        waves = (orders + pairs - 1) // pairs
        return market_price * (step_factor ** waves)

    if side == "SELL":
        sell_factor = Decimal("1") + half_spread
        step_factor = sell_factor * (Decimal("1") + red_line)
        if step_factor <= 1:
            return None
        projected_price = market_price
        projected_balance = balance
        for _ in range(500):
            sell_price = projected_price * sell_factor
            projected_balance -= Decimal(pairs) * lot_quote / sell_price
            projected_price *= step_factor
            if projected_balance <= threshold:
                return projected_price
        return None

    raise ValueError("side must be BUY or SELL")
