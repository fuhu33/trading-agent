"""Finnhub 财报日历接入测试。"""

from datetime import date, datetime

from trading_agent import fundamentals as f


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2099, 1, 1, tzinfo=tz)


class DummyYFTicker:
    """最小 yf.Ticker 替身，用于验证编排逻辑。"""

    def __init__(self, ticker: str, session=None):
        self.ticker = ticker
        self.session = session


def _base_info(_yf_obj):
    return {
        "sector": None,
        "industry": None,
        "current_price": 100.0,
        "recommendation_mean": None,
        "recommendation_key": None,
        "target_mean": None,
        "target_high": None,
        "target_low": None,
        "num_analysts": None,
    }


def test_finnhub_next_earnings_preserves_source_and_estimates(monkeypatch):
    """Finnhub 财报日历应输出来源、盘前盘后、EPS/营收预期。"""
    monkeypatch.setattr(f, "FINNHUB_API_KEY", "token")
    monkeypatch.setattr(f, "make_request", lambda *args, **kwargs: {
        "earningsCalendar": [
            {
                "date": "2099-01-10",
                "epsEstimate": 2.34,
                "revenueEstimate": 123456789,
                "hour": "amc",
                "quarter": 4,
                "year": 2098,
                "symbol": "AAPL",
            }
        ]
    })
    monkeypatch.setattr(f, "datetime", FixedDatetime)

    result = f.fetch_finnhub_earnings_calendar("AAPL")

    assert result == {
        "date": "2099-01-10",
        "days_until": 9,
        "in_window": True,
        "source": "finnhub",
        "hour": "amc",
        "eps_estimate": 2.34,
        "revenue_estimate": 123456789,
        "quarter": 4,
        "year": 2098,
    }


def test_yfinance_next_earnings_marks_source(monkeypatch):
    """yfinance 财报日也应标记来源，便于报告追踪。"""

    class YFObj:
        calendar = {"Earnings Date": [date(2099, 1, 10)]}

    monkeypatch.setattr(f, "datetime", FixedDatetime)

    result = f._extract_next_earnings(YFObj())

    assert result == {
        "date": "2099-01-10",
        "days_until": 9,
        "in_window": True,
        "source": "yfinance",
    }


def test_build_report_uses_finnhub_fallback_when_yfinance_calendar_missing(monkeypatch):
    """完整基本面工作流在 yfinance 无财报日时应接入 Finnhub 兜底。"""
    monkeypatch.setattr(f.yf, "Ticker", DummyYFTicker)
    monkeypatch.setattr(f, "_extract_info", lambda yf_obj: {
        **_base_info(yf_obj),
        "recommendation_mean": 1.5,
        "recommendation_key": "buy",
        "target_mean": 120.0,
    })
    monkeypatch.setattr(f, "_extract_earnings", lambda yf_obj: {"eps_surprise_pct": 12.0})
    monkeypatch.setattr(f, "_extract_next_earnings", lambda yf_obj: None)
    monkeypatch.setattr(f, "fetch_etf_trend", lambda etf: None)
    monkeypatch.setattr(f, "set_cached", lambda ticker, data: None)
    monkeypatch.setattr(f, "fetch_finnhub_earnings_calendar", lambda ticker: {
        "date": "2099-01-10",
        "days_until": 9,
        "in_window": True,
        "source": "finnhub",
        "hour": "amc",
        "eps_estimate": 2.34,
        "revenue_estimate": 123456789,
        "quarter": 4,
        "year": 2098,
    })

    report = f.build_fundamentals_report("AAPL", force_refresh=True)

    assert report["status"] == "success"
    assert report["next_earnings"]["source"] == "finnhub"
    assert report["next_earnings"]["hour"] == "amc"
    assert report["next_earnings"]["eps_estimate"] == 2.34
    assert any("盘后" in driver for driver in report["narrative"]["drivers"])
