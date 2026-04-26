"""任意美股 yfinance K 线兜底数据源测试。"""

from trading_agent import data as d


class FakeHistory:
    empty = False

    def __init__(self):
        self.rows = [
            ("2099-01-01", 10.0, 11.0, 9.5, 10.5, 1000.0),
            ("2099-01-02", 10.5, 12.0, 10.2, 11.8, 1500.0),
        ]

    def reset_index(self):
        return self

    def iterrows(self):
        for idx, (date, open_, high, low, close, volume) in enumerate(self.rows):
            yield idx, {
                "Date": date,
                "Open": open_,
                "High": high,
                "Low": low,
                "Close": close,
                "Volume": volume,
            }


class FakeTicker:
    def __init__(self, ticker, session=None):
        self.ticker = ticker
        self.session = session

    def history(self, period, interval, auto_adjust=False):
        assert period == "90d"
        assert interval == "1d"
        assert auto_adjust is False
        return FakeHistory()


def test_get_candle_data_falls_back_to_yfinance_for_non_bitget_symbol(monkeypatch):
    """不在 Bitget RWA 的美股应自动用 yfinance 现货日 K。"""
    monkeypatch.setattr(d, "lookup_symbol", lambda ticker: None)
    monkeypatch.setattr(d.yf, "Ticker", FakeTicker)

    report = d.get_candle_data("CRM", days=90)

    assert report["status"] == "success"
    assert report["ticker"] == "CRM"
    assert report["symbol"] == "CRM"
    assert report["source"] == "yfinance"
    assert report["group"] == "us_stock"
    assert report["tradable_on_bitget"] is False
    assert report["candles"][0]["open"] == 10.0
    assert report["latest"]["close"] == 11.8


def test_get_candle_data_marks_bitget_tradability_for_supported_stock(monkeypatch):
    """Bitget RWA 已支持的美股默认仍用 yfinance 分析，但保留 Bitget 合约映射。"""
    monkeypatch.setattr(d, "lookup_symbol", lambda ticker: {
        "symbol": "NVDAUSDT",
        "group": "stock",
        "baseCoin": "NVDA",
    })
    monkeypatch.setattr(d.yf, "Ticker", FakeTicker)

    report = d.get_candle_data("NVDA", days=90)

    assert report["source"] == "yfinance"
    assert report["symbol"] == "NVDA"
    assert report["tradable_on_bitget"] is True
    assert report["bitget_symbol"] == "NVDAUSDT"
