"""sentiment 模块单元测试。"""

import pandas as pd

from trading_agent.sentiment import (
    STATE_RECOVERY_CANDIDATE,
    SentimentParams,
    aggregate_daily_sentiment,
    build_market_sentiment_report_from_prices,
    build_sentiment_validation_report_from_prices,
    classify_sentiment_state,
    compute_bar_factors,
    compute_factor_frame,
    select_reference_universe,
)


def test_compute_bar_factors_identifies_pure_attack():
    params = SentimentParams()
    factors = compute_bar_factors(
        {"open": 100, "high": 106, "low": 99, "close": 104},
        params,
    )

    assert factors["valid_ohlc"] is True
    assert factors["raw_attack"] is True
    assert factors["pure_attack"] is True
    assert factors["failed_attack"] is False
    assert factors["pure_pullback"] is False


def test_compute_bar_factors_identifies_failed_attack():
    factors = compute_bar_factors(
        {"open": 100, "high": 106, "low": 99, "close": 102}
    )

    assert factors["raw_attack"] is True
    assert factors["pure_attack"] is False
    assert factors["failed_attack"] is True


def test_compute_bar_factors_identifies_pure_pullback():
    factors = compute_bar_factors(
        {"open": 100, "high": 104, "low": 92, "close": 94}
    )

    assert factors["pure_pullback"] is True
    assert factors["pure_attack"] is False


def test_compute_bar_factors_handles_invalid_ohlc_without_false_signal():
    factors = compute_bar_factors(
        {"open": 100, "high": 99, "low": 98, "close": 101}
    )

    assert factors["valid_ohlc"] is False
    assert factors["raw_attack"] is False
    assert factors["pure_attack"] is False
    assert factors["failed_attack"] is False
    assert factors["pure_pullback"] is False


def _price_rows():
    return pd.DataFrame([
        {"date": "2026-01-01", "ticker": "AAA", "open": 95, "high": 96, "low": 94, "close": 95, "volume": 100},
        {"date": "2026-01-01", "ticker": "BBB", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 100},
        {"date": "2026-01-01", "ticker": "CCC", "open": 105, "high": 106, "low": 104, "close": 105, "volume": 100},
        {"date": "2026-01-02", "ticker": "AAA", "open": 100, "high": 106, "low": 99, "close": 104, "volume": 100},
        {"date": "2026-01-02", "ticker": "BBB", "open": 100, "high": 106, "low": 99, "close": 102, "volume": 200},
        {"date": "2026-01-02", "ticker": "CCC", "open": 100, "high": 104, "low": 92, "close": 94, "volume": 300},
    ])


def test_aggregate_daily_sentiment_counts_core_ratios():
    frame = compute_factor_frame(_price_rows())
    result = aggregate_daily_sentiment(
        frame,
        "2026-01-02",
        universe=["AAA", "BBB", "CCC"],
    )

    assert result["effective_count"] == 3
    assert result["raw_attack_count"] == 3
    assert result["pure_attack_count"] == 1
    assert result["failed_attack_count"] == 2
    assert result["pure_pullback_count"] == 1
    assert result["raw_attack_ratio"] == 1.0
    assert result["pure_attack_ratio"] == 1 / 3
    assert result["failed_attack_ratio"] == 2 / 3
    assert result["pure_pullback_ratio"] == 1 / 3
    assert result["net_attack_sentiment"] == 0.0
    assert result["advance_ratio"] == 2 / 3


def test_select_reference_universe_uses_only_prior_data():
    params = SentimentParams(universe_lookback_days=1, min_universe_history=1)
    prices = pd.DataFrame([
        {"date": "2026-01-01", "ticker": "AAA", "close": 10, "volume": 100},
        {"date": "2026-01-01", "ticker": "BBB", "close": 10, "volume": 200},
        {"date": "2026-01-02", "ticker": "AAA", "close": 10, "volume": 10_000},
        {"date": "2026-01-02", "ticker": "BBB", "close": 10, "volume": 200},
    ])

    assert select_reference_universe(prices, "2026-01-02", 1, params) == ["BBB"]
    assert select_reference_universe(prices, "2026-01-03", 1, params) == ["AAA"]


def test_factor_frame_computes_high_low_and_ma20_repair_helpers():
    params = SentimentParams(high_low_window=3, ma_window=3)
    prices = pd.DataFrame([
        {"date": "2026-01-01", "ticker": "AAA", "open": 10, "high": 10.5, "low": 9.5, "close": 10, "volume": 100},
        {"date": "2026-01-02", "ticker": "AAA", "open": 10, "high": 10.6, "low": 9.4, "close": 9, "volume": 100},
        {"date": "2026-01-03", "ticker": "AAA", "open": 9, "high": 9.5, "low": 7.5, "close": 8, "volume": 100},
        {"date": "2026-01-04", "ticker": "AAA", "open": 8, "high": 12, "low": 7.9, "close": 11, "volume": 100},
    ])

    frame = compute_factor_frame(prices, params)
    latest = frame[frame["date"] == pd.Timestamp("2026-01-04")].iloc[0]

    assert bool(latest["high20"]) is True
    assert bool(latest["low20"]) is False
    assert bool(latest["above_ma20"]) is True
    assert bool(latest["reclaim_ma20"]) is True


def test_classify_sentiment_state_detects_recovery_candidate():
    params = SentimentParams(
        smooth_span=1,
        slope_days=1,
        percentile_lookback_days=5,
        cold_lookback_days=3,
        cold_low_percentile=70,
        cold_high_percentile=60,
    )
    history = pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=5),
        "pure_attack_ratio": [0.10, 0.09, 0.01, 0.04, 0.05],
        "pure_pullback_ratio": [0.10, 0.20, 0.30, 0.20, 0.10],
        "attack_failure_rate": [0.20, 0.50, 0.90, 0.70, 0.60],
        "low20_ratio": [0.10, 0.20, 0.50, 0.30, 0.10],
        "above_ma20_ratio": [0.10, 0.12, 0.14, 0.18, 0.24],
        "advance_ratio": [0.30, 0.35, 0.20, 0.40, 0.45],
    })
    history["net_attack_sentiment"] = (
        history["pure_attack_ratio"] - history["pure_pullback_ratio"]
    )

    state = classify_sentiment_state(history, params)

    assert state["state"] == STATE_RECOVERY_CANDIDATE
    assert state["recent_cold"] is True
    assert state["recovery_candidate"] is True
    assert state["recovery_confirmed"] is False


def test_build_market_sentiment_report_from_prices_includes_compare_breadth():
    params = SentimentParams(
        universe_lookback_days=1,
        min_universe_history=1,
        high_low_window=2,
        ma_window=2,
        percentile_lookback_days=3,
    )

    report = build_market_sentiment_report_from_prices(
        _price_rows(),
        as_of_date="2026-01-02",
        top_n=2,
        compare_top_n=(1, 3),
        params=params,
    )

    assert report["status"] == "success"
    assert report["date"] == "2026-01-02"
    assert report["reference"]["top_n"] == 2
    assert "pure_attack_ratio" in report["metrics"]
    assert set(report["breadth_compare"]) == {"1", "3"}
    assert "state" in report["trend"]


def test_build_sentiment_validation_report_from_prices_summarizes_benchmark_returns():
    params = SentimentParams(
        universe_lookback_days=1,
        min_universe_history=1,
        high_low_window=2,
        ma_window=2,
        percentile_lookback_days=3,
        slope_days=1,
        smooth_span=1,
    )
    prices = _price_rows()
    spy_rows = []
    for idx, date in enumerate(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]):
        close = 400 + idx * 2
        spy_rows.append({
            "date": date,
            "ticker": "SPY",
            "open": close - 1,
            "high": close + 1,
            "low": close - 2,
            "close": close,
            "volume": 1_000,
        })
    prices = pd.concat([prices, pd.DataFrame(spy_rows)], ignore_index=True)
    master = pd.DataFrame({
        "ticker": ["AAA", "BBB", "CCC"],
        "active": [True, True, True],
    })

    report = build_sentiment_validation_report_from_prices(
        prices,
        benchmark_tickers=("SPY",),
        forward_days=(1,),
        top_n=2,
        params=params,
        master=master,
    )

    assert report["status"] == "success"
    assert "SPY" in report["benchmarks"]
    assert report["benchmarks"]["SPY"]["states"]
