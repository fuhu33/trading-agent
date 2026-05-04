"""data 模块测试：Bitget 只做交易池，OHLCV 来自 yfinance。"""

import pandas as pd
import pytest

from trading_agent import data
from trading_agent.exceptions import ValidationError


def _symbol_info(ticker="AAPL", group="stock"):
    return {
        "baseCoin": ticker,
        "symbol": f"{ticker}USDT",
        "group": group,
    }


def _price_frame(ticker="AAPL", rows=3):
    return pd.DataFrame([
        {
            "date": f"2026-01-{idx + 1:02d}",
            "ticker": ticker,
            "open": 100 + idx,
            "high": 102 + idx,
            "low": 99 + idx,
            "close": 101 + idx,
            "volume": 1000 + idx,
        }
        for idx in range(rows)
    ])


def test_resolve_yfinance_symbol_uses_commodity_proxy():
    assert data.resolve_yfinance_symbol("XAU") == "GC=F"
    assert data.resolve_yfinance_symbol("COPPER") == "HG=F"
    assert data.resolve_yfinance_symbol("STXSTOCK") == "STX"


def test_get_candle_data_fetches_from_yfinance_after_bitget_pool_check(monkeypatch):
    calls = {}

    monkeypatch.setattr(data, "lookup_symbol", lambda ticker: _symbol_info(ticker))

    def fake_fetch(tickers, **kwargs):
        calls["tickers"] = tickers
        calls["kwargs"] = kwargs
        return _price_frame("AAPL", rows=5)

    monkeypatch.setattr(data, "fetch_yfinance_ohlcv", fake_fetch)

    report = data.get_candle_data("AAPL", days=3)

    assert calls["tickers"] == ["AAPL"]
    assert report["source"] == "yfinance"
    assert report["trade_pool_source"] == "bitget"
    assert report["symbol"] == "AAPL"
    assert report["trade_symbol"] == "AAPLUSDT"
    assert report["data_points"] == 3
    assert [item["date"] for item in report["candles"]] == [
        "2026-01-03",
        "2026-01-04",
        "2026-01-05",
    ]


def test_get_candle_data_uses_yfinance_override_for_trade_pool_symbol(monkeypatch):
    monkeypatch.setattr(data, "lookup_symbol", lambda ticker: _symbol_info("STXSTOCK"))
    monkeypatch.setattr(
        data,
        "fetch_yfinance_ohlcv",
        lambda tickers, **kwargs: _price_frame("STX", rows=3),
    )

    report = data.get_candle_data("STXSTOCK", days=2)

    assert report["ticker"] == "STXSTOCK"
    assert report["market_data_symbol"] == "STX"
    assert report["trade_symbol"] == "STXSTOCKUSDT"
    assert report["data_points"] == 2


def test_get_candle_data_rejects_ticker_outside_trade_pool(monkeypatch):
    monkeypatch.setattr(data, "lookup_symbol", lambda ticker: None)

    with pytest.raises(ValidationError):
        data.get_candle_data("NOTREAL")
