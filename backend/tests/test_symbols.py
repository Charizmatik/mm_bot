from app.exchanges.mexc import parse_symbols


def test_parse_symbols_returns_only_spot_pairs() -> None:
    result = parse_symbols({
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "baseAsset": "BTC",
                "quoteAsset": "USDT",
                "baseAssetPrecision": 8,
                "quotePrecision": 2,
                "permissions": ["SPOT"],
                "isSpotTradingAllowed": True,
            },
            {
                "symbol": "FUTURESONLY",
                "baseAsset": "FUTURES",
                "quoteAsset": "ONLY",
                "permissions": ["FUTURES"],
            },
            {
                "symbol": "DISABLEDUSDT",
                "baseAsset": "DISABLED",
                "quoteAsset": "USDT",
                "permissions": ["SPOT"],
                "isSpotTradingAllowed": False,
            },
        ]
    })

    assert len(result) == 1
    assert result[0].symbol == "BTCUSDT"
    assert result[0].base_asset == "BTC"
    assert result[0].quote_asset == "USDT"
    assert result[0].price_precision == 2
    assert result[0].quantity_precision == 8
