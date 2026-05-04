"""sentiment CLI/report 单元测试。"""

import sys

import pandas as pd

from trading_agent import sentiment


def _sample_prices() -> pd.DataFrame:
    rows = []
    tickers = ["AAPL", "MSFT", "NVDA", "SPY"]
    for day in range(1, 28):
        date = f"2026-01-{day:02d}"
        for idx, ticker in enumerate(tickers):
            base = 100 + day + idx * 10
            rows.append({
                "date": date,
                "ticker": ticker,
                "open": base,
                "high": base * 1.04,
                "low": base * 0.97,
                "close": base * (1.02 if ticker not in {"NVDA", "SPY"} else 0.98),
                "volume": 1_000 + idx * 500,
            })
    return pd.DataFrame(rows)


def test_build_market_sentiment_report_uses_mocked_yfinance(monkeypatch):
    monkeypatch.setattr(
        sentiment,
        "fetch_yfinance_ohlcv",
        lambda *args, **kwargs: _sample_prices(),
    )

    report = sentiment.build_market_sentiment_report(
        ["AAPL", "MSFT", "NVDA"],
        as_of_date="2026-01-27",
        top_n=2,
        compare_top_n=(1, 3),
    )

    assert report["status"] == "success"
    assert report["source"] == "yfinance"
    assert report["reference"]["top_n"] == 2
    assert report["reference"]["input_ticker_count"] == 3
    assert set(report["breadth_compare"]) == {"1", "3"}


def test_format_market_sentiment_report_includes_core_lines():
    report = {
        "status": "success",
        "date": "2026-01-27",
        "source": "yfinance",
        "reference": {
            "top_n": 2,
            "effective_count": 2,
            "universe_count": 2,
            "input_ticker_count": 3,
        },
        "metrics": {
            "pure_attack_ratio": 0.5,
            "failed_attack_ratio": 0.25,
            "pure_pullback_ratio": 0.0,
            "net_attack_sentiment": 0.5,
            "advance_ratio": 0.75,
            "low20_ratio": 0.1,
            "above_ma20_ratio": 0.6,
        },
        "trend": {"state": "RISK_ON"},
        "breadth_compare": {"1": {"state": "RISK_ON"}},
    }

    output = sentiment.format_market_sentiment_report(report)

    assert "美股情绪报告" in output
    assert "RISK_ON" in output
    assert "PureAttack" in output
    assert "宽窄对比" in output


def test_sentiment_main_prints_json(monkeypatch, capsys):
    monkeypatch.setattr(
        sentiment,
        "fetch_yfinance_ohlcv",
        lambda *args, **kwargs: _sample_prices(),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "trading-agent sentiment",
            "--tickers",
            "AAPL,MSFT,NVDA",
            "--date",
            "2026-01-27",
            "--top",
            "2",
            "--compare",
            "1,3",
            "--json",
            "--validate",
            "--benchmarks",
            "SPY",
            "--forward",
            "1",
        ],
    )

    sentiment.main()
    output = capsys.readouterr().out

    assert '"status": "success"' in output
    assert '"source": "yfinance"' in output
    assert '"validation"' in output
