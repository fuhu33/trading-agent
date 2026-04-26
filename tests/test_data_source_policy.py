"""数据源策略测试。"""

from trading_agent import data as d


class FakeHistory:
    empty = False

    def __init__(self, close=101.0):
        self.rows = [("2099-01-01", 100.0, 102.0, 99.0, close, 1000.0)]

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
        return FakeHistory()


def test_stock_supported_on_bitget_uses_yfinance_as_analysis_source(monkeypatch):
    """美股即使已上线 Bitget，默认也用 yfinance 做主分析源。"""
    monkeypatch.setattr(d, "lookup_symbol", lambda ticker: {
        "symbol": "NVDAUSDT",
        "group": "stock",
        "baseCoin": "NVDA",
    })
    monkeypatch.setattr(d.yf, "Ticker", FakeTicker)
    monkeypatch.setattr(d, "fetch_all_candles", lambda symbol, days: (_ for _ in ()).throw(AssertionError("should not call bitget")))

    report = d.get_candle_data("NVDA", days=90)

    assert report["source"] == "yfinance"
    assert report["analysis_source"] == "yfinance"
    assert report["symbol"] == "NVDA"
    assert report["group"] == "stock"
    assert report["tradable_on_bitget"] is True
    assert report["bitget_symbol"] == "NVDAUSDT"


def test_etf_supported_on_bitget_uses_yfinance_as_analysis_source(monkeypatch):
    """ETF 即使已上线 Bitget，默认也用 yfinance 做主分析源。"""
    monkeypatch.setattr(d, "lookup_symbol", lambda ticker: {
        "symbol": "QQQUSDT",
        "group": "etf",
        "baseCoin": "QQQ",
    })
    monkeypatch.setattr(d.yf, "Ticker", FakeTicker)

    report = d.get_candle_data("QQQ", days=90)

    assert report["source"] == "yfinance"
    assert report["group"] == "etf"
    assert report["tradable_on_bitget"] is True
    assert report["bitget_symbol"] == "QQQUSDT"


def test_commodity_keeps_bitget_as_analysis_source(monkeypatch):
    """商品仍使用 Bitget K 线，避免 yfinance ticker 映射歧义。"""
    monkeypatch.setattr(d, "lookup_symbol", lambda ticker: {
        "symbol": "XAUUSDT",
        "group": "commodity",
        "baseCoin": "XAU",
    })
    monkeypatch.setattr(d, "fetch_all_candles", lambda symbol, days: [
        {
            "timestamp": 4070908800000,
            "date": "2099-01-01",
            "open": 2000.0,
            "high": 2010.0,
            "low": 1990.0,
            "close": 2005.0,
            "volume": 1000.0,
            "quote_volume": 2005000.0,
        }
    ])

    report = d.get_candle_data("XAU", days=90)

    assert report["source"] == "bitget"
    assert report["analysis_source"] == "bitget"
    assert report["tradable_on_bitget"] is True
    assert report["bitget_symbol"] == "XAUUSDT"


def test_non_bitget_us_stock_uses_yfinance_and_marks_not_tradable(monkeypatch):
    """未上线 Bitget 的普通美股用 yfinance，并标记不可在 Bitget RWA 交易。"""
    monkeypatch.setattr(d, "lookup_symbol", lambda ticker: None)
    monkeypatch.setattr(d.yf, "Ticker", FakeTicker)

    report = d.get_candle_data("CRM", days=90)

    assert report["source"] == "yfinance"
    assert report["analysis_source"] == "yfinance"
    assert report["group"] == "us_stock"
    assert report["tradable_on_bitget"] is False
    assert report["bitget_symbol"] is None
