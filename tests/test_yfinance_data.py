"""yfinance_data 模块单元测试。"""

import json

import pandas as pd

from trading_agent.yfinance_data import (
    fetch_yfinance_ohlcv,
    filter_common_stock_master,
    load_us_equity_master,
    normalize_yfinance_ohlcv,
    validate_ohlcv_frame,
)


def test_normalize_single_level_yfinance_frame():
    raw = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [105.0],
            "Low": [99.0],
            "Close": [104.0],
            "Volume": [1_000],
        },
        index=pd.to_datetime(["2026-01-02"]),
    )

    result = normalize_yfinance_ohlcv(raw, "aapl")

    assert list(result.columns) == ["date", "ticker", "open", "high", "low", "close", "volume"]
    assert result.iloc[0]["ticker"] == "AAPL"
    assert result.iloc[0]["close"] == 104.0


def test_normalize_multiindex_grouped_by_column():
    columns = pd.MultiIndex.from_tuples([
        ("Open", "AAPL"),
        ("High", "AAPL"),
        ("Low", "AAPL"),
        ("Close", "AAPL"),
        ("Volume", "AAPL"),
        ("Open", "MSFT"),
        ("High", "MSFT"),
        ("Low", "MSFT"),
        ("Close", "MSFT"),
        ("Volume", "MSFT"),
    ])
    raw = pd.DataFrame(
        [[100, 105, 99, 104, 1000, 200, 206, 198, 204, 2000]],
        columns=columns,
        index=pd.to_datetime(["2026-01-02"]),
    )

    result = normalize_yfinance_ohlcv(raw, ["AAPL", "MSFT"])

    assert set(result["ticker"]) == {"AAPL", "MSFT"}
    assert result[result["ticker"] == "MSFT"].iloc[0]["close"] == 204


def test_normalize_multiindex_grouped_by_ticker():
    columns = pd.MultiIndex.from_tuples([
        ("AAPL", "Open"),
        ("AAPL", "High"),
        ("AAPL", "Low"),
        ("AAPL", "Close"),
        ("AAPL", "Volume"),
        ("MSFT", "Open"),
        ("MSFT", "High"),
        ("MSFT", "Low"),
        ("MSFT", "Close"),
        ("MSFT", "Volume"),
    ])
    raw = pd.DataFrame(
        [[100, 105, 99, 104, 1000, 200, 206, 198, 204, 2000]],
        columns=columns,
        index=pd.to_datetime(["2026-01-02"]),
    )

    result = normalize_yfinance_ohlcv(raw, ["AAPL", "MSFT"])

    assert len(result) == 2
    assert result[result["ticker"] == "AAPL"].iloc[0]["open"] == 100


def test_normalize_yfinance_drops_all_empty_failed_download_rows():
    columns = pd.MultiIndex.from_tuples([
        ("Open", "AAPL"),
        ("High", "AAPL"),
        ("Low", "AAPL"),
        ("Close", "AAPL"),
        ("Volume", "AAPL"),
        ("Open", "MSFT"),
        ("High", "MSFT"),
        ("Low", "MSFT"),
        ("Close", "MSFT"),
        ("Volume", "MSFT"),
    ])
    raw = pd.DataFrame(
        [[None, None, None, None, None, 200, 206, 198, 204, 2000]],
        columns=columns,
        index=pd.to_datetime(["2026-01-02"]),
    )

    result = normalize_yfinance_ohlcv(raw, ["AAPL", "MSFT"])

    assert list(result["ticker"]) == ["MSFT"]


def _raw_download_for(tickers: list[str]) -> pd.DataFrame:
    columns = []
    values = []
    for index, ticker in enumerate(tickers):
        base = 100 + index * 10
        for field, value in [
            ("Open", base),
            ("High", base + 5),
            ("Low", base - 1),
            ("Close", base + 4),
            ("Volume", 1_000 + index),
        ]:
            columns.append((field, ticker))
            values.append(value)
    return pd.DataFrame(
        [values],
        columns=pd.MultiIndex.from_tuples(columns),
        index=pd.to_datetime(["2026-01-02"]),
    )


def test_fetch_yfinance_ohlcv_chunks_downloads(monkeypatch):
    calls = []

    def fake_download(ticker_list, **kwargs):
        calls.append(list(ticker_list))
        return _raw_download_for(ticker_list)

    monkeypatch.setattr("trading_agent.yfinance_data._download_yfinance_raw", fake_download)

    result = fetch_yfinance_ohlcv(
        ["AAPL", "MSFT", "NVDA"],
        period="5d",
        chunk_size=2,
        use_cache=False,
        retry_sleep=0,
    )

    assert calls == [["AAPL", "MSFT"], ["NVDA"]]
    assert set(result["ticker"]) == {"AAPL", "MSFT", "NVDA"}


def test_fetch_yfinance_ohlcv_retries_empty_chunk(monkeypatch):
    calls = []

    def fake_download(ticker_list, **kwargs):
        calls.append(list(ticker_list))
        if len(calls) == 1:
            return pd.DataFrame()
        return _raw_download_for(ticker_list)

    monkeypatch.setattr("trading_agent.yfinance_data._download_yfinance_raw", fake_download)

    result = fetch_yfinance_ohlcv(
        ["AAPL"],
        period="5d",
        retries=1,
        retry_sleep=0,
        use_cache=False,
    )

    assert len(calls) == 2
    assert list(result["ticker"]) == ["AAPL"]


def test_fetch_yfinance_ohlcv_uses_cache(monkeypatch, tmp_path):
    calls = []

    def fake_download(ticker_list, **kwargs):
        calls.append(list(ticker_list))
        return _raw_download_for(ticker_list)

    monkeypatch.setattr("trading_agent.yfinance_data._download_yfinance_raw", fake_download)
    first = fetch_yfinance_ohlcv(
        ["AAPL"],
        period="5d",
        use_cache=True,
        cache_dir=tmp_path,
        retry_sleep=0,
    )
    second = fetch_yfinance_ohlcv(
        ["AAPL"],
        period="5d",
        use_cache=True,
        cache_dir=tmp_path,
        retry_sleep=0,
    )

    assert len(calls) == 1
    assert first.equals(second)


def test_load_us_equity_master_from_json_list(tmp_path):
    path = tmp_path / "universe.json"
    path.write_text(
        json.dumps([
            {"ticker": "AAPL", "name": "Apple Inc.", "active": True},
            {"ticker": "SPY", "name": "SPDR S&P 500 ETF", "is_etf": True},
        ]),
        encoding="utf-8",
    )

    master = load_us_equity_master(path)

    assert list(master["ticker"]) == ["AAPL", "SPY"]
    filtered = filter_common_stock_master(master)
    assert list(filtered["ticker"]) == ["AAPL"]


def test_load_us_equity_master_from_nasdaq_style_pipe_file(tmp_path):
    path = tmp_path / "nasdaqlisted.txt"
    path.write_text(
        "Symbol|Security Name|ETF|Test Issue|Financial Status\n"
        "AAPL|Apple Inc. Common Stock|N|N|N\n"
        "QQQ|Invesco QQQ Trust ETF|Y|N|N\n"
        "TEST|Test Issue Common Stock|N|Y|N\n",
        encoding="utf-8",
    )

    master = load_us_equity_master(path)
    filtered = filter_common_stock_master(master)

    assert list(filtered["ticker"]) == ["AAPL"]


def test_filter_common_stock_master_can_exclude_adr():
    master = pd.DataFrame([
        {"ticker": "TSM", "name": "Taiwan Semiconductor ADR", "active": True},
        {"ticker": "NVDA", "name": "NVIDIA Corporation Common Stock", "active": True},
    ])

    filtered = filter_common_stock_master(master, include_adr=False)

    assert list(filtered["ticker"]) == ["NVDA"]


def test_validate_ohlcv_frame_reports_partial_quality():
    frame = pd.DataFrame([
        {"date": "2026-01-02", "ticker": "AAPL", "open": 100, "high": 105, "low": 99, "close": 104, "volume": 1000},
        {"date": "2026-01-02", "ticker": "BAD", "open": 100, "high": 99, "low": 98, "close": 101, "volume": 1000},
    ])

    result = validate_ohlcv_frame(
        frame,
        expected_tickers=["AAPL", "MSFT"],
        min_valid_ratio=0.75,
    )

    assert result["status"] == "partial"
    assert result["valid_rows"] == 1
    assert result["total_rows"] == 2
    assert "MSFT" in result["missing_tickers"]
    assert result["warnings"]
