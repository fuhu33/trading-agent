"""yfinance OHLCV helpers for US market sentiment research.

This module keeps network fetching separate from the pure sentiment formulas.
The normalizers are intentionally testable without hitting Yahoo.
"""

from __future__ import annotations

import json
import hashlib
import re
import time
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import yfinance as yf

try:
    from curl_cffi import requests as _curl_requests

    _YF_SESSION = _curl_requests.Session(impersonate="chrome")
except Exception:
    _YF_SESSION = None


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
YFINANCE_TZ_CACHE_DIR = CONFIG_DIR / "yfinance_cache"
YFINANCE_PRICE_CACHE_DIR = CONFIG_DIR / "yfinance_price_cache"
CACHE_TTL_SECONDS = 6 * 3600

OHLCV_COLUMNS = ["date", "ticker", "open", "high", "low", "close", "volume"]
_FIELD_ALIASES = {
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
}


try:
    yf.set_tz_cache_location(str(YFINANCE_TZ_CACHE_DIR))
except Exception:
    pass


def normalize_ticker(ticker: Any) -> str:
    """Normalize a ticker for internal matching."""
    return str(ticker).strip().upper()


def _normalize_field_name(value: Any) -> str:
    text = str(value).strip().lower().replace("_", " ")
    text = re.sub(r"\s+", " ", text)
    return text


def _empty_price_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=OHLCV_COLUMNS)


def _field_alias(value: Any) -> str | None:
    return _FIELD_ALIASES.get(_normalize_field_name(value))


def _ticker_list(tickers: str | Iterable[str] | None) -> list[str]:
    if tickers is None:
        return []
    if isinstance(tickers, str):
        raw = re.split(r"[\s,]+", tickers.strip())
    else:
        raw = list(tickers)
    return [normalize_ticker(t) for t in raw if str(t).strip()]


def _chunked(items: list[str], chunk_size: int) -> list[list[str]]:
    chunk_size = max(int(chunk_size), 1)
    return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]


def _detect_field_level(columns: pd.MultiIndex) -> int | None:
    best_level = None
    best_count = -1
    for level in range(columns.nlevels):
        values = {_field_alias(item) for item in columns.get_level_values(level)}
        count = len({v for v in values if v is not None})
        if count > best_count:
            best_level = level
            best_count = count
    return best_level if best_count > 0 else None


def _detect_ticker_level(columns: pd.MultiIndex, field_level: int,
                         expected_tickers: list[str]) -> int:
    expected = set(expected_tickers)
    candidates = [level for level in range(columns.nlevels) if level != field_level]
    if not candidates:
        return 0

    best_level = candidates[0]
    best_score = -1
    for level in candidates:
        values = {normalize_ticker(item) for item in columns.get_level_values(level)}
        score = len(values & expected) if expected else len(values)
        if score > best_score:
            best_level = level
            best_score = score
    return best_level


def _frame_from_ticker_columns(raw: pd.DataFrame,
                               tickers: list[str]) -> pd.DataFrame:
    columns = raw.columns
    assert isinstance(columns, pd.MultiIndex)

    field_level = _detect_field_level(columns)
    if field_level is None:
        return _empty_price_frame()
    ticker_level = _detect_ticker_level(columns, field_level, tickers)

    frames = []
    for ticker_value in columns.get_level_values(ticker_level).unique():
        ticker = normalize_ticker(ticker_value)
        field_columns = {}
        for column in columns:
            if normalize_ticker(column[ticker_level]) != ticker:
                continue
            field = _field_alias(column[field_level])
            if field is None:
                continue
            field_columns[field] = raw[column]

        if not field_columns:
            continue
        sub = pd.DataFrame(field_columns, index=raw.index)
        sub["date"] = raw.index
        sub["ticker"] = ticker
        frames.append(sub)

    if not frames:
        return _empty_price_frame()
    return pd.concat(frames, ignore_index=True, sort=False)


def _frame_from_single_columns(raw: pd.DataFrame,
                               tickers: list[str]) -> pd.DataFrame:
    field_columns = {}
    for column in raw.columns:
        field = _field_alias(column)
        if field is not None:
            field_columns[field] = raw[column]

    if not field_columns:
        return _empty_price_frame()

    ticker = tickers[0] if tickers else "UNKNOWN"
    result = pd.DataFrame(field_columns, index=raw.index)
    result["date"] = raw.index
    result["ticker"] = ticker
    return result


def normalize_yfinance_ohlcv(raw: pd.DataFrame,
                             tickers: str | Iterable[str] | None = None
                             ) -> pd.DataFrame:
    """Normalize yfinance download output into long-form OHLCV rows.

    Supports single-level columns, MultiIndex grouped by column, and MultiIndex
    grouped by ticker.
    """
    if raw is None or raw.empty:
        return _empty_price_frame()

    if set(OHLCV_COLUMNS).issubset(raw.columns):
        result = raw[OHLCV_COLUMNS].copy()
        result["date"] = pd.to_datetime(result["date"]).dt.tz_localize(None).dt.normalize()
        result["ticker"] = result["ticker"].map(normalize_ticker)
        for column in ["open", "high", "low", "close", "volume"]:
            result[column] = pd.to_numeric(result[column], errors="coerce")
        result = result.dropna(
            subset=["open", "high", "low", "close", "volume"],
            how="all",
        )
        result = result.dropna(subset=["date", "ticker"])
        return result.sort_values(["ticker", "date"]).reset_index(drop=True)

    expected_tickers = _ticker_list(tickers)
    if isinstance(raw.columns, pd.MultiIndex):
        result = _frame_from_ticker_columns(raw, expected_tickers)
    else:
        result = _frame_from_single_columns(raw, expected_tickers)

    if result.empty:
        return _empty_price_frame()

    for column in OHLCV_COLUMNS:
        if column not in result.columns:
            result[column] = np.nan

    result = result[OHLCV_COLUMNS].copy()
    result["date"] = pd.to_datetime(result["date"]).dt.tz_localize(None).dt.normalize()
    result["ticker"] = result["ticker"].map(normalize_ticker)
    for column in ["open", "high", "low", "close", "volume"]:
        result[column] = pd.to_numeric(result[column], errors="coerce")

    result = result.dropna(
        subset=["open", "high", "low", "close", "volume"],
        how="all",
    )
    result = result.dropna(subset=["date", "ticker"])
    result = result.sort_values(["ticker", "date"]).reset_index(drop=True)
    return result


def _download_yfinance_raw(ticker_list: list[str],
                           start: str | None = None,
                           end: str | None = None,
                           period: str | None = None,
                           interval: str = "1d",
                           auto_adjust: bool = True,
                           threads: bool = True,
                           progress: bool = False) -> pd.DataFrame:
    kwargs = {
        "tickers": ticker_list,
        "start": start,
        "end": end,
        "period": period,
        "interval": interval,
        "group_by": "column",
        "auto_adjust": auto_adjust,
        "actions": False,
        "threads": threads,
        "progress": progress,
        "multi_level_index": True,
    }
    if _YF_SESSION is not None:
        kwargs["session"] = _YF_SESSION

    raw = yf.download(**kwargs)
    return raw


def _cache_token(ticker_list: list[str],
                 start: str | None,
                 end: str | None,
                 period: str | None,
                 interval: str,
                 auto_adjust: bool) -> str:
    token = {
        "tickers": sorted(ticker_list),
        "start": start,
        "end": end,
        "period": period,
        "interval": interval,
        "auto_adjust": auto_adjust,
    }
    raw = json.dumps(token, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _cache_path(cache_dir: str | Path,
                ticker_list: list[str],
                start: str | None,
                end: str | None,
                period: str | None,
                interval: str,
                auto_adjust: bool) -> Path:
    return Path(cache_dir) / (
        f"ohlcv_{_cache_token(ticker_list, start, end, period, interval, auto_adjust)}.csv"
    )


def _load_cached_prices(path: Path, cache_ttl_seconds: int | None) -> pd.DataFrame | None:
    if not path.exists():
        return None
    if cache_ttl_seconds is not None:
        age = time.time() - path.stat().st_mtime
        if age > cache_ttl_seconds:
            return None
    try:
        frame = pd.read_csv(path, parse_dates=["date"])
    except Exception:
        return None
    return normalize_yfinance_ohlcv(frame)


def _save_cached_prices(path: Path, frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _fetch_yfinance_chunk(ticker_list: list[str],
                          start: str | None = None,
                          end: str | None = None,
                          period: str | None = None,
                          interval: str = "1d",
                          auto_adjust: bool = True,
                          threads: bool = True,
                          progress: bool = False,
                          retries: int = 2,
                          retry_sleep: float = 2.0) -> pd.DataFrame:
    attempts = max(retries, 0) + 1
    best = _empty_price_frame()

    for attempt in range(attempts):
        try:
            raw = _download_yfinance_raw(
                ticker_list,
                start=start,
                end=end,
                period=period,
                interval=interval,
                auto_adjust=auto_adjust,
                threads=threads,
                progress=progress,
            )
            frame = normalize_yfinance_ohlcv(raw, ticker_list)
            if len(frame) > len(best):
                best = frame

            present = set(frame["ticker"]) if not frame.empty else set()
            if set(ticker_list).issubset(present):
                return frame
        except Exception:
            pass

        if attempt < attempts - 1 and retry_sleep > 0:
            time.sleep(retry_sleep)

    return best


def fetch_yfinance_ohlcv(tickers: str | Iterable[str],
                         start: str | None = None,
                         end: str | None = None,
                         period: str | None = None,
                         interval: str = "1d",
                         auto_adjust: bool = True,
                         threads: bool = True,
                         progress: bool = False,
                         chunk_size: int = 80,
                         retries: int = 2,
                         retry_sleep: float = 2.0,
                         use_cache: bool = True,
                         refresh_cache: bool = False,
                         cache_dir: str | Path = YFINANCE_PRICE_CACHE_DIR,
                         cache_ttl_seconds: int | None = CACHE_TTL_SECONDS
                         ) -> pd.DataFrame:
    """Fetch OHLCV from yfinance with chunking, retries, and optional cache.

    yfinance treats ``end`` as exclusive for daily data, so callers that want to
    include a date should pass the next calendar day.
    """
    ticker_list = _ticker_list(tickers)
    if not ticker_list:
        return _empty_price_frame()

    frames = []
    for chunk in _chunked(ticker_list, chunk_size):
        path = _cache_path(cache_dir, chunk, start, end, period, interval, auto_adjust)
        cached = None if refresh_cache or not use_cache else _load_cached_prices(
            path,
            cache_ttl_seconds,
        )
        if cached is not None:
            frames.append(cached)
            continue

        frame = _fetch_yfinance_chunk(
            chunk,
            start=start,
            end=end,
            period=period,
            interval=interval,
            auto_adjust=auto_adjust,
            threads=threads,
            progress=progress,
            retries=retries,
            retry_sleep=retry_sleep,
        )
        frames.append(frame)
        if use_cache:
            _save_cached_prices(path, frame)

    if not frames:
        return _empty_price_frame()
    result = pd.concat(frames, ignore_index=True, sort=False)
    result = result.drop_duplicates(subset=["date", "ticker"], keep="last")
    return result.sort_values(["ticker", "date"]).reset_index(drop=True)


def _snake_case(value: Any) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def _bool_series(series: pd.Series, default: bool = False) -> pd.Series:
    truthy = {"Y", "YES", "TRUE", "1"}
    falsy = {"N", "NO", "FALSE", "0"}

    def convert(value: Any) -> bool:
        if pd.isna(value):
            return default
        if isinstance(value, bool):
            return value
        text = str(value).strip().upper()
        if text in truthy:
            return True
        if text in falsy:
            return False
        return bool(value)

    return series.map(convert)


def _load_json_records(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        records = (
            data.get("symbols")
            or data.get("tickers")
            or data.get("data")
            or data.get("records")
            or []
        )
    else:
        records = []

    if records and isinstance(records[0], str):
        return [{"ticker": item} for item in records]
    return [dict(item) for item in records if isinstance(item, dict)]


def _load_tabular_master(path: Path) -> pd.DataFrame:
    separator = "|" if path.suffix.lower() in {".txt", ".psv"} else ","
    return pd.read_csv(path, sep=separator)


def normalize_us_equity_master(master: pd.DataFrame) -> pd.DataFrame:
    """Normalize common ticker master columns into a stable schema."""
    if master.empty:
        return pd.DataFrame(columns=[
            "ticker",
            "name",
            "exchange",
            "asset_type",
            "is_etf",
            "is_test_issue",
            "financial_status",
            "active",
        ])

    df = master.copy()
    df.columns = [_snake_case(column) for column in df.columns]

    ticker_sources = [
        "ticker",
        "symbol",
        "nasdaq_symbol",
        "act_symbol",
        "cqs_symbol",
    ]
    ticker_column = next((column for column in ticker_sources if column in df), None)
    if ticker_column is None:
        raise ValueError("ticker master does not contain a ticker/symbol column")

    df["ticker"] = df[ticker_column].map(normalize_ticker)

    if "name" not in df:
        if "security_name" in df:
            df["name"] = df["security_name"]
        elif "company_name" in df:
            df["name"] = df["company_name"]
        else:
            df["name"] = ""

    if "exchange" not in df:
        if "listing_exchange" in df:
            df["exchange"] = df["listing_exchange"]
        else:
            df["exchange"] = ""

    if "asset_type" not in df:
        df["asset_type"] = "stock"

    if "is_etf" not in df:
        if "etf" in df:
            df["is_etf"] = _bool_series(df["etf"])
        else:
            df["is_etf"] = False
    else:
        df["is_etf"] = _bool_series(df["is_etf"])

    if "is_test_issue" not in df:
        if "test_issue" in df:
            df["is_test_issue"] = _bool_series(df["test_issue"])
        else:
            df["is_test_issue"] = False
    else:
        df["is_test_issue"] = _bool_series(df["is_test_issue"])

    if "financial_status" not in df:
        df["financial_status"] = ""

    if "active" not in df:
        df["active"] = True
    else:
        df["active"] = _bool_series(df["active"], default=True)

    keep = [
        "ticker",
        "name",
        "exchange",
        "asset_type",
        "is_etf",
        "is_test_issue",
        "financial_status",
        "active",
    ]
    result = df[keep].copy()
    result = result[result["ticker"].astype(bool)]
    result = result.drop_duplicates(subset=["ticker"], keep="first")
    return result.reset_index(drop=True)


def load_us_equity_master(path: str | Path) -> pd.DataFrame:
    """Load and normalize a static US equity ticker master."""
    path = Path(path)
    if path.suffix.lower() == ".json":
        frame = pd.DataFrame(_load_json_records(path))
    elif path.suffix.lower() in {".csv", ".txt", ".psv"}:
        frame = _load_tabular_master(path)
    else:
        raise ValueError(f"unsupported ticker master format: {path.suffix}")
    return normalize_us_equity_master(frame)


def filter_common_stock_master(master: pd.DataFrame,
                               include_adr: bool = True) -> pd.DataFrame:
    """Filter normalized master records to common-stock-like symbols."""
    df = normalize_us_equity_master(master)
    if df.empty:
        return df

    name = df["name"].astype(str).str.lower()
    asset_type = df["asset_type"].astype(str).str.lower()
    financial_status = df["financial_status"].astype(str).str.upper()

    excluded_name = name.str.contains(
        r"etf|fund|warrant|preferred|preference|unit|right|note|debenture",
        regex=True,
        na=False,
    )
    if not include_adr:
        excluded_name = excluded_name | name.str.contains(r"\badr\b", regex=True, na=False)

    excluded_type = asset_type.str.contains(
        r"etf|fund|warrant|preferred|unit|right",
        regex=True,
        na=False,
    )
    normal_financial = financial_status.isin({"", "N", "NORMAL", "NAN"})

    keep = (
        df["active"].astype(bool)
        & ~df["is_etf"].astype(bool)
        & ~df["is_test_issue"].astype(bool)
        & ~excluded_name
        & ~excluded_type
        & normal_financial
    )
    return df[keep].reset_index(drop=True)


def validate_ohlcv_frame(price_frame: pd.DataFrame,
                         expected_tickers: Iterable[str] | None = None,
                         min_valid_ratio: float = 0.90) -> dict:
    """Return lightweight data-quality diagnostics for a long OHLCV frame."""
    required = set(OHLCV_COLUMNS)
    missing_columns = sorted(required - set(price_frame.columns))
    if missing_columns:
        return {
            "status": "error",
            "missing_columns": missing_columns,
            "valid_rows": 0,
            "total_rows": len(price_frame),
            "valid_ratio": 0.0,
            "warnings": [f"missing columns: {', '.join(missing_columns)}"],
        }

    df = price_frame.copy()
    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    valid_ohlc = (
        (df["open"] > 0)
        & (df["high"] > 0)
        & (df["low"] > 0)
        & (df["close"] > 0)
        & (df["high"] >= df[["open", "close"]].max(axis=1))
        & (df["low"] <= df[["open", "close"]].min(axis=1))
        & (df["volume"] >= 0)
    )
    total_rows = len(df)
    valid_rows = int(valid_ohlc.sum())
    valid_ratio = valid_rows / total_rows if total_rows else 0.0

    warnings = []
    if valid_ratio < min_valid_ratio:
        warnings.append(
            f"valid OHLCV ratio {valid_ratio:.1%} below {min_valid_ratio:.1%}"
        )

    expected = set(_ticker_list(expected_tickers))
    present = set(df["ticker"].astype(str).map(normalize_ticker)) if "ticker" in df else set()
    missing_tickers = sorted(expected - present)
    if missing_tickers:
        warnings.append(f"missing tickers: {', '.join(missing_tickers[:10])}")

    return {
        "status": "success" if not warnings else "partial",
        "valid_rows": valid_rows,
        "total_rows": total_rows,
        "valid_ratio": valid_ratio,
        "missing_tickers": missing_tickers,
        "warnings": warnings,
    }
