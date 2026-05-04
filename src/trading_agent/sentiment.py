"""Market sentiment factors based on US equity OHLCV data."""

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import timedelta
from math import isfinite
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .yfinance_data import (
    fetch_yfinance_ohlcv,
    filter_common_stock_master,
    load_us_equity_master,
    validate_ohlcv_frame,
)


@dataclass(frozen=True)
class SentimentParams:
    """Configuration for market sentiment factor calculations."""

    attack_threshold: float = 0.03
    pullback_threshold: float = 0.03
    hold_threshold: float = 0.50
    body_ratio_threshold: float = 0.30
    universe_lookback_days: int = 20
    min_universe_history: int = 5
    percentile_lookback_days: int = 90
    smooth_span: int = 3
    slope_days: int = 3
    high_low_window: int = 20
    ma_window: int = 20
    cold_lookback_days: int = 5
    cold_low_percentile: float = 20.0
    cold_high_percentile: float = 80.0


STATE_RISK_OFF = "RISK_OFF"
STATE_COLD = "COLD"
STATE_RECOVERY_CANDIDATE = "RECOVERY_CANDIDATE"
STATE_RISK_ON = "RISK_ON"
STATE_DIVERGENCE = "DIVERGENCE"


def _to_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(result):
        return None
    return result


def _safe_div(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _valid_ohlc(open_: float | None, high: float | None,
                low: float | None, close: float | None) -> bool:
    if open_ is None or high is None or low is None or close is None:
        return False
    if open_ <= 0 or high <= 0 or low <= 0 or close <= 0:
        return False
    return bool(high >= max(open_, close) and low <= min(open_, close))


def compute_bar_factors(row: dict | pd.Series,
                        params: SentimentParams | None = None) -> dict:
    """Compute attack/pullback factors for one OHLC bar."""
    params = params or SentimentParams()
    open_ = _to_float(row.get("open"))
    high = _to_float(row.get("high"))
    low = _to_float(row.get("low"))
    close = _to_float(row.get("close"))

    base = {
        "valid_ohlc": False,
        "attack_amp": None,
        "pullback_amp": None,
        "attack_hold": None,
        "giveback": None,
        "bull_body_ratio": None,
        "bear_hold": None,
        "bear_body_ratio": None,
        "raw_attack": False,
        "pure_attack": False,
        "failed_attack": False,
        "pure_pullback": False,
    }

    if not _valid_ohlc(open_, high, low, close):
        return base

    assert open_ is not None
    assert high is not None
    assert low is not None
    assert close is not None

    day_range = high - low
    attack_path = high - open_
    bear_path = open_ - low

    attack_amp = high / open_ - 1
    pullback_amp = high / close - 1
    attack_hold = _safe_div(close - open_, attack_path) if attack_path > 0 else None
    giveback = _safe_div(high - close, attack_path) if attack_path > 0 else None
    bull_body_ratio = _safe_div(close - open_, day_range) if day_range > 0 else None
    bear_hold = _safe_div(open_ - close, bear_path) if bear_path > 0 else None
    bear_body_ratio = _safe_div(open_ - close, day_range) if day_range > 0 else None

    raw_attack = bool(attack_path > 0 and attack_amp >= params.attack_threshold)
    pure_attack = bool(
        raw_attack
        and close > open_
        and attack_hold is not None
        and attack_hold >= params.hold_threshold
        and bull_body_ratio is not None
        and bull_body_ratio >= params.body_ratio_threshold
    )
    failed_attack = bool(
        raw_attack
        and pullback_amp >= params.pullback_threshold
        and giveback is not None
        and giveback >= params.hold_threshold
    )
    pure_pullback = bool(
        pullback_amp >= params.pullback_threshold
        and close < open_
        and bear_hold is not None
        and bear_hold >= params.hold_threshold
        and bear_body_ratio is not None
        and bear_body_ratio >= params.body_ratio_threshold
    )

    base.update({
        "valid_ohlc": True,
        "attack_amp": attack_amp,
        "pullback_amp": pullback_amp,
        "attack_hold": attack_hold,
        "giveback": giveback,
        "bull_body_ratio": bull_body_ratio,
        "bear_hold": bear_hold,
        "bear_body_ratio": bear_body_ratio,
        "raw_attack": raw_attack,
        "pure_attack": pure_attack,
        "failed_attack": failed_attack,
        "pure_pullback": pure_pullback,
    })
    return base


def _rolling_by_ticker(df: pd.DataFrame, column: str, window: int,
                       method: str) -> pd.Series:
    grouped = df.groupby("ticker", sort=False)[column]
    if method == "mean":
        return grouped.transform(lambda s: s.rolling(window, min_periods=window).mean())
    if method == "max":
        return grouped.transform(lambda s: s.rolling(window, min_periods=window).max())
    if method == "min":
        return grouped.transform(lambda s: s.rolling(window, min_periods=window).min())
    raise ValueError(f"unknown rolling method: {method}")


def compute_factor_frame(price_frame: pd.DataFrame,
                         params: SentimentParams | None = None) -> pd.DataFrame:
    """Compute single-name factors and breadth helper columns for a price panel."""
    params = params or SentimentParams()
    required = {"date", "ticker", "open", "high", "low", "close", "volume"}
    missing = required - set(price_frame.columns)
    if missing:
        raise ValueError(f"price_frame missing required columns: {sorted(missing)}")

    df = price_frame.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["ticker"] = df["ticker"].astype(str).str.upper()
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)

    factors = pd.DataFrame(
        [compute_bar_factors(row, params) for row in df.to_dict("records")]
    )
    df = pd.concat([df, factors], axis=1)

    grouped = df.groupby("ticker", sort=False)
    df["prev_close"] = grouped["close"].shift(1)
    df["daily_return"] = df["close"] / df["prev_close"] - 1
    df["dollar_volume"] = df["close"] * df["volume"]
    df["advance"] = df["daily_return"] > 0
    df["decline"] = df["daily_return"] < 0

    df["ma20"] = _rolling_by_ticker(df, "close", params.ma_window, "mean")
    grouped = df.groupby("ticker", sort=False)
    df["prev_ma20"] = grouped["ma20"].shift(1)
    df["above_ma20"] = df["close"] > df["ma20"]
    df["prev_above_ma20"] = df["prev_close"] > df["prev_ma20"]
    df["reclaim_ma20"] = df["above_ma20"] & ~df["prev_above_ma20"].fillna(False)
    df["lose_ma20"] = ~df["above_ma20"] & df["prev_above_ma20"].fillna(False)

    df["high20_level"] = _rolling_by_ticker(
        df, "high", params.high_low_window, "max"
    )
    df["low20_level"] = _rolling_by_ticker(
        df, "low", params.high_low_window, "min"
    )
    df["high20"] = df["high"] >= df["high20_level"]
    df["low20"] = df["low"] <= df["low20_level"]

    return df


def select_reference_universe(price_frame: pd.DataFrame, as_of_date: Any,
                              top_n: int = 200,
                              params: SentimentParams | None = None,
                              master: pd.DataFrame | None = None) -> list[str]:
    """Select the top dollar-volume universe using only data before as_of_date."""
    params = params or SentimentParams()
    df = price_frame.copy()
    required = {"date", "ticker", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"price_frame missing required columns: {sorted(missing)}")

    df["date"] = pd.to_datetime(df["date"])
    df["ticker"] = df["ticker"].astype(str).str.upper()
    target = pd.to_datetime(as_of_date).normalize()
    df = df[df["date"].dt.normalize() < target]

    if master is not None and "ticker" in master.columns:
        allowed = set(master["ticker"].astype(str).str.upper())
        if "active" in master.columns:
            active = master[master["active"].astype(bool)]
            allowed = set(active["ticker"].astype(str).str.upper())
        df = df[df["ticker"].isin(allowed)]

    if df.empty:
        return []

    df["dollar_volume"] = df["close"] * df["volume"]
    df = df[np.isfinite(df["dollar_volume"]) & (df["dollar_volume"] > 0)]
    if df.empty:
        return []

    recent = (
        df.sort_values(["ticker", "date"])
        .groupby("ticker", sort=False)
        .tail(params.universe_lookback_days)
    )
    stats = recent.groupby("ticker").agg(
        avg_dollar_volume=("dollar_volume", "mean"),
        observations=("dollar_volume", "count"),
    )
    stats = stats[stats["observations"] >= params.min_universe_history]
    stats = stats.sort_values(
        ["avg_dollar_volume", "observations"],
        ascending=[False, False],
    )
    return stats.head(top_n).index.tolist()


def _bool_count(df: pd.DataFrame, column: str) -> int:
    if column not in df:
        return 0
    return int(df[column].fillna(False).astype(bool).sum())


def _ratio(count: int, total: int) -> float | None:
    return None if total <= 0 else count / total


def aggregate_daily_sentiment(factor_frame: pd.DataFrame, date: Any,
                              universe: list[str] | None = None,
                              params: SentimentParams | None = None) -> dict:
    """Aggregate per-name factors into one daily sentiment snapshot."""
    params = params or SentimentParams()
    df = factor_frame.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["ticker"] = df["ticker"].astype(str).str.upper()
    target = pd.to_datetime(date).normalize()
    rows = df[df["date"].dt.normalize() == target]

    if universe is not None:
        allowed = {ticker.upper() for ticker in universe}
        rows = rows[rows["ticker"].isin(allowed)]

    if "valid_ohlc" in rows:
        rows = rows[rows["valid_ohlc"].fillna(False).astype(bool)]

    total = len(rows)
    raw_count = _bool_count(rows, "raw_attack")
    pure_attack_count = _bool_count(rows, "pure_attack")
    failed_attack_count = _bool_count(rows, "failed_attack")
    pure_pullback_count = _bool_count(rows, "pure_pullback")
    advance_count = _bool_count(rows, "advance")
    decline_count = _bool_count(rows, "decline")
    high20_count = _bool_count(rows, "high20")
    low20_count = _bool_count(rows, "low20")
    above_ma20_count = _bool_count(rows, "above_ma20")
    reclaim_ma20_count = _bool_count(rows, "reclaim_ma20")
    lose_ma20_count = _bool_count(rows, "lose_ma20")

    raw_attack_ratio = _ratio(raw_count, total)
    pure_attack_ratio = _ratio(pure_attack_count, total)
    failed_attack_ratio = _ratio(failed_attack_count, total)
    pure_pullback_ratio = _ratio(pure_pullback_count, total)
    net_attack = None
    if pure_attack_ratio is not None and pure_pullback_ratio is not None:
        net_attack = pure_attack_ratio - pure_pullback_ratio

    total_dollar_volume = rows.get("dollar_volume", pd.Series(dtype=float)).sum()
    if total_dollar_volume > 0:
        if "advance" in rows:
            advance_mask = rows["advance"].fillna(False).astype(bool)
        else:
            advance_mask = pd.Series(False, index=rows.index)
        if "decline" in rows:
            decline_mask = rows["decline"].fillna(False).astype(bool)
        else:
            decline_mask = pd.Series(False, index=rows.index)
        up_dollar_volume = rows.loc[advance_mask, "dollar_volume"].sum()
        down_dollar_volume = rows.loc[decline_mask, "dollar_volume"].sum()
        up_dollar_volume_ratio = up_dollar_volume / total_dollar_volume
        down_dollar_volume_ratio = down_dollar_volume / total_dollar_volume
    else:
        up_dollar_volume_ratio = None
        down_dollar_volume_ratio = None

    return {
        "date": target.strftime("%Y-%m-%d"),
        "effective_count": total,
        "raw_attack_count": raw_count,
        "pure_attack_count": pure_attack_count,
        "failed_attack_count": failed_attack_count,
        "pure_pullback_count": pure_pullback_count,
        "raw_attack_ratio": raw_attack_ratio,
        "pure_attack_ratio": pure_attack_ratio,
        "failed_attack_ratio": failed_attack_ratio,
        "pure_pullback_ratio": pure_pullback_ratio,
        "net_attack_sentiment": net_attack,
        "attack_quality": (
            pure_attack_count / raw_count if raw_count > 0 else 0.0
        ),
        "attack_failure_rate": (
            failed_attack_count / raw_count if raw_count > 0 else 0.0
        ),
        "advance_ratio": _ratio(advance_count, total),
        "decline_ratio": _ratio(decline_count, total),
        "up_dollar_volume_ratio": up_dollar_volume_ratio,
        "down_dollar_volume_ratio": down_dollar_volume_ratio,
        "high20_ratio": _ratio(high20_count, total),
        "low20_ratio": _ratio(low20_count, total),
        "net_high_low20": (
            _ratio(high20_count, total) - _ratio(low20_count, total)
            if total > 0 else None
        ),
        "above_ma20_ratio": _ratio(above_ma20_count, total),
        "reclaim_ma20_ratio": _ratio(reclaim_ma20_count, total),
        "lose_ma20_ratio": _ratio(lose_ma20_count, total),
        "params": {
            "attack_threshold": params.attack_threshold,
            "pullback_threshold": params.pullback_threshold,
            "hold_threshold": params.hold_threshold,
            "body_ratio_threshold": params.body_ratio_threshold,
        },
    }


def _rolling_percent_rank(series: pd.Series, window: int) -> pd.Series:
    def pct_rank(values: np.ndarray) -> float:
        current = values[-1]
        values = values[~np.isnan(values)]
        if len(values) == 0 or np.isnan(current):
            return np.nan
        return float((values <= current).sum() / len(values) * 100)

    return series.rolling(window, min_periods=1).apply(pct_rank, raw=True)


def compute_trend_features(history: pd.DataFrame,
                           params: SentimentParams | None = None
                           ) -> pd.DataFrame:
    """Add EMA, slope, percentile rank, and cold-point helper columns."""
    params = params or SentimentParams()
    df = history.copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

    specs = {
        "net_attack_sentiment": "net_attack",
        "pure_attack_ratio": "pure_attack",
        "pure_pullback_ratio": "pure_pullback",
        "attack_failure_rate": "failure",
        "low20_ratio": "low20",
        "above_ma20_ratio": "above_ma20",
    }

    for source, label in specs.items():
        if source not in df:
            df[source] = np.nan
        numeric = pd.to_numeric(df[source], errors="coerce")
        ema_col = f"{label}_ema{params.smooth_span}"
        slope_col = f"{label}_slope_{params.slope_days}"
        rank_col = f"{label}_pct_rank"
        df[ema_col] = numeric.ewm(span=params.smooth_span, adjust=False).mean()
        df[slope_col] = df[ema_col] - df[ema_col].shift(params.slope_days)
        df[rank_col] = _rolling_percent_rank(
            numeric,
            params.percentile_lookback_days,
        )

    df["cold_point"] = (
        (df["pure_attack_pct_rank"] <= params.cold_low_percentile)
        & (
            (df["pure_pullback_pct_rank"] >= params.cold_high_percentile)
            | (df["failure_pct_rank"] >= params.cold_high_percentile)
            | (df["low20_pct_rank"] >= params.cold_high_percentile)
            | (df["net_attack_pct_rank"] <= params.cold_low_percentile)
        )
    )
    return df


def _latest_value(row: pd.Series, column: str, default: float = np.nan) -> float:
    value = row.get(column, default)
    result = _to_float(value)
    return default if result is None else result


def classify_sentiment_state(history: pd.DataFrame,
                             params: SentimentParams | None = None) -> dict:
    """Classify the latest market sentiment state from history."""
    params = params or SentimentParams()
    if history.empty:
        return {
            "state": STATE_DIVERGENCE,
            "message": "empty sentiment history",
            "cold_point": False,
            "recovery_candidate": False,
            "recovery_confirmed": False,
        }

    df = compute_trend_features(history, params)
    latest = df.iloc[-1]
    recent = df.tail(params.cold_lookback_days)

    net_slope = _latest_value(latest, f"net_attack_slope_{params.slope_days}", 0.0)
    pullback_slope = _latest_value(latest, f"pure_pullback_slope_{params.slope_days}", 0.0)
    failure_slope = _latest_value(latest, f"failure_slope_{params.slope_days}", 0.0)
    low20_slope = _latest_value(latest, f"low20_slope_{params.slope_days}", 0.0)
    above_ma20_slope = _latest_value(latest, f"above_ma20_slope_{params.slope_days}", 0.0)

    pure_attack_rank = _latest_value(latest, "pure_attack_pct_rank", 50.0)
    pure_pullback_rank = _latest_value(latest, "pure_pullback_pct_rank", 50.0)
    failure_rank = _latest_value(latest, "failure_pct_rank", 50.0)
    low20_rank = _latest_value(latest, "low20_pct_rank", 50.0)
    net_rank = _latest_value(latest, "net_attack_pct_rank", 50.0)
    advance_ratio = _latest_value(latest, "advance_ratio", 0.0)

    cold_point = bool(latest.get("cold_point", False))
    recent_cold = bool(recent["cold_point"].fillna(False).astype(bool).any())
    bad_rank_high = (
        pure_pullback_rank >= params.cold_high_percentile
        or failure_rank >= params.cold_high_percentile
        or low20_rank >= params.cold_high_percentile
    )

    risk_off = bool(bad_rank_high and net_slope < 0)
    recovery_candidate = bool(
        recent_cold
        and net_slope > 0
        and pullback_slope < 0
        and failure_slope <= 0
        and low20_slope < 0
        and above_ma20_slope >= 0
    )
    recovery_confirmed = bool(
        recovery_candidate
        and pure_attack_rank >= 40
        and failure_rank <= 60
        and advance_ratio >= 0.50
        and above_ma20_slope > 0
    )
    divergence = bool(pure_attack_rank >= 60 and failure_rank >= 70)

    if risk_off:
        state = STATE_RISK_OFF
    elif recovery_confirmed:
        state = STATE_RISK_ON
    elif recovery_candidate:
        state = STATE_RECOVERY_CANDIDATE
    elif divergence:
        state = STATE_DIVERGENCE
    elif cold_point or (pure_attack_rank <= params.cold_low_percentile and bad_rank_high):
        state = STATE_COLD
    elif net_rank >= 50 and advance_ratio >= 0.50 and above_ma20_slope >= 0:
        state = STATE_RISK_ON
    else:
        state = STATE_DIVERGENCE

    return {
        "state": state,
        "cold_point": cold_point,
        "recent_cold": recent_cold,
        "recovery_candidate": recovery_candidate,
        "recovery_confirmed": recovery_confirmed,
        "risk_off": risk_off,
        "divergence": divergence,
        "net_attack_slope_3": net_slope,
        "pullback_slope_3": pullback_slope,
        "failure_slope_3": failure_slope,
        "low20_slope_3": low20_slope,
        "above_ma20_slope_3": above_ma20_slope,
        "net_attack_pct_rank": net_rank,
        "pure_attack_pct_rank": pure_attack_rank,
        "pure_pullback_pct_rank": pure_pullback_rank,
        "failure_pct_rank": failure_rank,
        "low20_pct_rank": low20_rank,
    }


def compute_sentiment_history(price_frame: pd.DataFrame,
                              dates: list[Any] | None = None,
                              top_n: int = 200,
                              params: SentimentParams | None = None,
                              master: pd.DataFrame | None = None
                              ) -> pd.DataFrame:
    """Build a daily sentiment history from a long-form price frame."""
    params = params or SentimentParams()
    factor_frame = compute_factor_frame(price_frame, params)
    if dates is None:
        dates = sorted(factor_frame["date"].dropna().unique())

    records = []
    for date in dates:
        universe = select_reference_universe(
            price_frame,
            date,
            top_n=top_n,
            params=params,
            master=master,
        )
        record = aggregate_daily_sentiment(
            factor_frame,
            date,
            universe=universe,
            params=params,
        )
        record["top_n"] = top_n
        record["universe_count"] = len(universe)
        records.append(record)

    history = pd.DataFrame(records)
    if not history.empty:
        history = compute_trend_features(history, params)
    return history


def build_market_sentiment_report_from_prices(
    price_frame: pd.DataFrame,
    as_of_date: Any | None = None,
    top_n: int = 200,
    compare_top_n: tuple[int, ...] = (100, 500),
    params: SentimentParams | None = None,
    master: pd.DataFrame | None = None,
) -> dict:
    """Build a structured market sentiment report from prepared OHLCV data."""
    params = params or SentimentParams()
    df = price_frame.copy()
    if df.empty:
        return {
            "status": "error",
            "message": "empty price frame",
        }

    df["date"] = pd.to_datetime(df["date"])
    target = (
        pd.to_datetime(as_of_date).normalize()
        if as_of_date is not None
        else df["date"].max().normalize()
    )

    dates = sorted(date for date in df["date"].dt.normalize().unique() if date <= target)
    if not dates:
        return {
            "status": "error",
            "message": f"no price data on or before {target.strftime('%Y-%m-%d')}",
        }

    main_history = compute_sentiment_history(
        df,
        dates=dates,
        top_n=top_n,
        params=params,
        master=master,
    )
    main_latest = main_history.iloc[-1].to_dict() if not main_history.empty else {}
    main_state = classify_sentiment_state(main_history, params)
    main_universe = select_reference_universe(
        df,
        dates[-1],
        top_n=top_n,
        params=params,
        master=master,
    )

    compare = {}
    for compare_n in compare_top_n:
        compare_history = compute_sentiment_history(
            df,
            dates=dates,
            top_n=compare_n,
            params=params,
            master=master,
        )
        compare_state = classify_sentiment_state(compare_history, params)
        compare_latest = (
            compare_history.iloc[-1].to_dict() if not compare_history.empty else {}
        )
        compare[str(compare_n)] = {
            "state": compare_state["state"],
            "effective_count": compare_latest.get("effective_count"),
            "universe_count": compare_latest.get("universe_count"),
            "net_attack_sentiment": compare_latest.get("net_attack_sentiment"),
            "advance_ratio": compare_latest.get("advance_ratio"),
            "low20_ratio": compare_latest.get("low20_ratio"),
            "above_ma20_ratio": compare_latest.get("above_ma20_ratio"),
        }

    metrics = {
        key: main_latest.get(key)
        for key in [
            "raw_attack_ratio",
            "pure_attack_ratio",
            "failed_attack_ratio",
            "pure_pullback_ratio",
            "advance_ratio",
            "up_dollar_volume_ratio",
            "high20_ratio",
            "low20_ratio",
            "above_ma20_ratio",
            "net_attack_sentiment",
            "attack_quality",
            "attack_failure_rate",
            "reclaim_ma20_ratio",
            "lose_ma20_ratio",
        ]
    }

    return {
        "status": "success",
        "date": target.strftime("%Y-%m-%d"),
        "source": "prepared_ohlcv",
        "reference": {
            "top_n": top_n,
            "lookback_days": params.universe_lookback_days,
            "effective_count": main_latest.get("effective_count"),
            "universe_count": main_latest.get("universe_count"),
            "selected_tickers": main_universe,
        },
        "metrics": metrics,
        "trend": main_state,
        "breadth_compare": compare,
    }


def compute_state_history(history: pd.DataFrame,
                          params: SentimentParams | None = None) -> pd.DataFrame:
    """Classify sentiment state for each row using only history up to that row."""
    params = params or SentimentParams()
    if history.empty:
        return pd.DataFrame(columns=["date", "state"])

    rows = []
    ordered = history.copy()
    ordered["date"] = pd.to_datetime(ordered["date"])
    ordered = ordered.sort_values("date").reset_index(drop=True)
    for idx in range(len(ordered)):
        prefix = ordered.iloc[:idx + 1].copy()
        state = classify_sentiment_state(prefix, params)
        rows.append({
            "date": ordered.iloc[idx]["date"],
            "state": state["state"],
            "cold_point": state.get("cold_point", False),
            "recovery_candidate": state.get("recovery_candidate", False),
            "recovery_confirmed": state.get("recovery_confirmed", False),
            "risk_off": state.get("risk_off", False),
        })
    return pd.DataFrame(rows)


def evaluate_state_forward_returns(state_history: pd.DataFrame,
                                   price_frame: pd.DataFrame,
                                   benchmark_ticker: str,
                                   forward_days: tuple[int, ...] = (1, 3, 5)
                                   ) -> dict:
    """Summarize benchmark forward returns by sentiment state."""
    if state_history.empty or price_frame.empty:
        return {"benchmark": benchmark_ticker.upper(), "states": {}}

    ticker = benchmark_ticker.upper()
    prices = price_frame.copy()
    prices["date"] = pd.to_datetime(prices["date"]).dt.normalize()
    prices["ticker"] = prices["ticker"].astype(str).str.upper()
    bench = (
        prices[prices["ticker"] == ticker]
        .sort_values("date")[["date", "close"]]
        .dropna()
        .reset_index(drop=True)
    )
    if bench.empty:
        return {
            "benchmark": ticker,
            "states": {},
            "warning": "benchmark not found in price frame",
        }

    merged = state_history.copy()
    merged["date"] = pd.to_datetime(merged["date"]).dt.normalize()
    merged = merged.merge(bench, on="date", how="left")

    result = {"benchmark": ticker, "states": {}}
    for days in forward_days:
        merged[f"fwd_{days}d"] = merged["close"].shift(-days) / merged["close"] - 1
        valid = merged.dropna(subset=[f"fwd_{days}d", "state"])
        for state, group in valid.groupby("state"):
            bucket = result["states"].setdefault(state, {})
            returns = group[f"fwd_{days}d"]
            bucket[f"{days}d"] = {
                "count": int(len(returns)),
                "mean": float(returns.mean()),
                "median": float(returns.median()),
                "hit_rate": float((returns > 0).mean()),
            }
    return result


def build_sentiment_validation_report_from_prices(
    price_frame: pd.DataFrame,
    benchmark_tickers: tuple[str, ...] = ("SPY", "QQQ"),
    forward_days: tuple[int, ...] = (1, 3, 5),
    top_n: int = 200,
    params: SentimentParams | None = None,
    master: pd.DataFrame | None = None,
) -> dict:
    """Build a lightweight historical validation report from prepared prices."""
    params = params or SentimentParams()
    if price_frame.empty:
        return {"status": "error", "message": "empty price frame"}

    df = price_frame.copy()
    df["date"] = pd.to_datetime(df["date"])
    dates = sorted(df["date"].dt.normalize().dropna().unique())
    history = compute_sentiment_history(
        df,
        dates=dates,
        top_n=top_n,
        params=params,
        master=master,
    )
    state_history = compute_state_history(history, params)
    benchmarks = {
        ticker.upper(): evaluate_state_forward_returns(
            state_history,
            df,
            ticker,
            forward_days=forward_days,
        )
        for ticker in benchmark_tickers
    }
    state_counts = (
        state_history["state"].value_counts().to_dict()
        if not state_history.empty else {}
    )
    return {
        "status": "success",
        "top_n": top_n,
        "state_counts": state_counts,
        "forward_days": list(forward_days),
        "benchmarks": benchmarks,
    }


def _parse_int_tuple(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    result = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        result.append(int(item))
    return tuple(result)


def _parse_str_tuple(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip().upper() for item in value.split(",") if item.strip())


def _read_plain_ticker_file(path: Path) -> list[str]:
    tickers = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tickers.extend(part.strip().upper() for part in line.split(",") if part.strip())
    return tickers


def load_reference_tickers(source: str,
                           include_adr: bool = True) -> tuple[list[str], pd.DataFrame | None]:
    """Load reference tickers from a CSV string, plain list, or ticker master file."""
    source = source.strip()
    if not source:
        return [], None

    path = Path(source)
    if path.exists():
        if path.suffix.lower() in {".json", ".csv"}:
            master = filter_common_stock_master(
                load_us_equity_master(path),
                include_adr=include_adr,
            )
            return master["ticker"].tolist(), master
        if path.suffix.lower() in {".txt", ".lst"}:
            try:
                master = filter_common_stock_master(
                    load_us_equity_master(path),
                    include_adr=include_adr,
                )
                if not master.empty:
                    return master["ticker"].tolist(), master
            except Exception:
                pass
            return _read_plain_ticker_file(path), None
        raise ValueError(f"unsupported ticker source file: {path}")

    tickers = [item.strip().upper() for item in source.split(",") if item.strip()]
    return tickers, None


def build_market_sentiment_report(
    tickers: list[str],
    as_of_date: Any | None = None,
    top_n: int = 200,
    compare_top_n: tuple[int, ...] = (100, 500),
    params: SentimentParams | None = None,
    master: pd.DataFrame | None = None,
    period: str = "1y",
    history_days: int = 420,
    chunk_size: int = 80,
    retries: int = 2,
    retry_sleep: float = 2.0,
    use_cache: bool = True,
    refresh_cache: bool = False,
    validate: bool = False,
    benchmark_tickers: tuple[str, ...] = ("SPY", "QQQ"),
    forward_days: tuple[int, ...] = (1, 3, 5),
) -> dict:
    """Fetch yfinance OHLCV and build a market sentiment report."""
    params = params or SentimentParams()
    if not tickers:
        return {
            "status": "error",
            "message": "empty reference ticker list",
        }

    target = pd.to_datetime(as_of_date).normalize() if as_of_date is not None else None
    fetch_tickers = list(dict.fromkeys(
        [ticker.upper() for ticker in tickers]
        + [ticker.upper() for ticker in benchmark_tickers if validate]
    ))
    if target is not None:
        end = (target + timedelta(days=1)).strftime("%Y-%m-%d")
        start = (target - timedelta(days=history_days)).strftime("%Y-%m-%d")
        prices = fetch_yfinance_ohlcv(
            fetch_tickers,
            start=start,
            end=end,
            chunk_size=chunk_size,
            retries=retries,
            retry_sleep=retry_sleep,
            use_cache=use_cache,
            refresh_cache=refresh_cache,
        )
    else:
        prices = fetch_yfinance_ohlcv(
            fetch_tickers,
            period=period,
            chunk_size=chunk_size,
            retries=retries,
            retry_sleep=retry_sleep,
            use_cache=use_cache,
            refresh_cache=refresh_cache,
        )

    quality = validate_ohlcv_frame(prices, expected_tickers=fetch_tickers)
    report_master = master
    if report_master is None and validate:
        report_master = pd.DataFrame({
            "ticker": [ticker.upper() for ticker in tickers],
            "active": [True] * len(tickers),
        })
    report = build_market_sentiment_report_from_prices(
        prices,
        as_of_date=target,
        top_n=top_n,
        compare_top_n=compare_top_n,
        params=params,
        master=report_master,
    )
    if report.get("status") != "success":
        report["data_quality"] = quality
        return report

    report["source"] = "yfinance"
    report["data_quality"] = quality
    report["reference"]["input_ticker_count"] = len(tickers)
    report["warnings"] = list(quality.get("warnings", []))
    if validate:
        report["validation"] = build_sentiment_validation_report_from_prices(
            prices,
            benchmark_tickers=benchmark_tickers,
            forward_days=forward_days,
            top_n=top_n,
            params=params,
            master=report_master,
        )

    if quality.get("status") == "partial":
        report["status"] = "partial"
    return report


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        if pd.isna(value):
            return "n/a"
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_num(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        if pd.isna(value):
            return "n/a"
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "n/a"


def format_market_sentiment_report(report: dict) -> str:
    """Format a compact CLI report."""
    if report.get("status") == "error":
        return f"美股情绪报告: ERROR\n原因: {report.get('message', 'unknown error')}"

    metrics = report.get("metrics", {})
    trend = report.get("trend", {})
    reference = report.get("reference", {})
    lines = [
        f"美股情绪报告 ({report.get('date', 'n/a')})",
        f"状态: {trend.get('state', 'n/a')} | source={report.get('source', 'n/a')}",
        (
            "参考池: "
            f"Top{reference.get('top_n')} "
            f"effective={reference.get('effective_count')} "
            f"universe={reference.get('universe_count')} "
            f"input={reference.get('input_ticker_count', 'n/a')}"
        ),
        "",
        "核心指标:",
        f"- PureAttack: {_fmt_pct(metrics.get('pure_attack_ratio'))}",
        f"- FailedAttack: {_fmt_pct(metrics.get('failed_attack_ratio'))}",
        f"- PurePullback: {_fmt_pct(metrics.get('pure_pullback_ratio'))}",
        f"- NetAttack: {_fmt_num(metrics.get('net_attack_sentiment'))}",
        f"- Advance: {_fmt_pct(metrics.get('advance_ratio'))}",
        f"- Low20: {_fmt_pct(metrics.get('low20_ratio'))}",
        f"- AboveMA20: {_fmt_pct(metrics.get('above_ma20_ratio'))}",
        "",
        "趋势:",
        f"- net_slope_3: {_fmt_num(trend.get('net_attack_slope_3'))}",
        f"- pullback_slope_3: {_fmt_num(trend.get('pullback_slope_3'))}",
        f"- failure_slope_3: {_fmt_num(trend.get('failure_slope_3'))}",
        f"- low20_slope_3: {_fmt_num(trend.get('low20_slope_3'))}",
        f"- above_ma20_slope_3: {_fmt_num(trend.get('above_ma20_slope_3'))}",
    ]

    compare = report.get("breadth_compare", {})
    if compare:
        lines.extend(["", "宽窄对比:"])
        for top_n, item in compare.items():
            lines.append(
                f"- Top{top_n}: {item.get('state')} "
                f"net={_fmt_num(item.get('net_attack_sentiment'))} "
                f"advance={_fmt_pct(item.get('advance_ratio'))} "
                f"low20={_fmt_pct(item.get('low20_ratio'))} "
                f"aboveMA20={_fmt_pct(item.get('above_ma20_ratio'))}"
            )

    warnings = report.get("warnings") or []
    if warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(f"- {warning}" for warning in warnings)

    validation = report.get("validation")
    if isinstance(validation, dict) and validation.get("status") == "success":
        lines.extend(["", "历史验证样本:"])
        counts = validation.get("state_counts", {})
        if counts:
            lines.append(
                "- states: "
                + ", ".join(f"{state}={count}" for state, count in counts.items())
            )
        for ticker, data in validation.get("benchmarks", {}).items():
            states = data.get("states", {})
            recovery = states.get(STATE_RECOVERY_CANDIDATE, {})
            first_horizon = next(iter(recovery.values()), None)
            if first_horizon:
                lines.append(
                    f"- {ticker} {STATE_RECOVERY_CANDIDATE}: "
                    f"mean={_fmt_pct(first_horizon.get('mean'))} "
                    f"hit={_fmt_pct(first_horizon.get('hit_rate'))} "
                    f"n={first_horizon.get('count')}"
                )

    return "\n".join(lines)


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if pd.isna(value):
        return None
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="计算 yfinance 美股参考池情绪指标")
    parser.add_argument(
        "--tickers",
        required=True,
        help="参考股票池：逗号分隔 ticker，或 json/csv/txt 文件路径",
    )
    parser.add_argument("--date", help="报告日期 YYYY-MM-DD，默认最近可用交易日")
    parser.add_argument("--top", type=int, default=200, help="主参考池 TopN")
    parser.add_argument("--compare", default="100,500", help="对照 TopN，如 100,500")
    parser.add_argument("--period", default="1y", help="未指定 --date 时的 yfinance period")
    parser.add_argument("--history-days", type=int, default=420,
                        help="指定 --date 时向前拉取的日历天数")
    parser.add_argument("--chunk-size", type=int, default=80,
                        help="yfinance 每批下载 ticker 数")
    parser.add_argument("--retries", type=int, default=2,
                        help="每个 yfinance 分块失败后的重试次数")
    parser.add_argument("--retry-sleep", type=float, default=2.0,
                        help="yfinance 重试间隔秒数")
    parser.add_argument("--no-cache", action="store_true",
                        help="禁用 yfinance 价格缓存")
    parser.add_argument("--refresh-cache", action="store_true",
                        help="忽略已有缓存并重新下载")
    parser.add_argument("--validate", action="store_true",
                        help="附加按状态统计的轻量历史验证")
    parser.add_argument("--benchmarks", default="SPY,QQQ",
                        help="历史验证基准 ticker，如 SPY,QQQ")
    parser.add_argument("--forward", default="1,3,5",
                        help="历史验证 forward days，如 1,3,5")
    parser.add_argument("--exclude-adr", action="store_true",
                        help="ticker master 过滤时排除 ADR")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    try:
        tickers, master = load_reference_tickers(
            args.tickers,
            include_adr=not args.exclude_adr,
        )
        report = build_market_sentiment_report(
            tickers,
            as_of_date=args.date,
            top_n=args.top,
            compare_top_n=_parse_int_tuple(args.compare),
            master=master,
            period=args.period,
            history_days=args.history_days,
            chunk_size=args.chunk_size,
            retries=args.retries,
            retry_sleep=args.retry_sleep,
            use_cache=not args.no_cache,
            refresh_cache=args.refresh_cache,
            validate=args.validate,
            benchmark_tickers=_parse_str_tuple(args.benchmarks),
            forward_days=_parse_int_tuple(args.forward),
        )
    except Exception as exc:
        report = {"status": "error", "message": str(exc)}

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=_json_default))
    else:
        print(format_market_sentiment_report(report))

    if report.get("status") == "error":
        sys.exit(1)
