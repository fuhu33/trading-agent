"""yfinance 日K数据获取.

Bitget 在本系统中只用于维护可交易池；所有 OHLCV 行情统一从
yfinance 获取，避免把交易所合约报价混入美股/ETF/商品分析口径。

用法 (CLI):
    uv run trading-agent data NVDA            # 获取 NVDA 最近 90 天日K
    uv run trading-agent data XAU --days 120  # 使用 yfinance 黄金代理合约
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from .exceptions import DataError, ValidationError
from .symbols import lookup_symbol
from .yfinance_data import fetch_yfinance_ohlcv, normalize_ticker


# Bitget baseCoin -> yfinance symbol. Stocks/ETFs generally use the same ticker.
YFINANCE_SYMBOL_OVERRIDES = {
    "COPPER": "HG=F",
    "NATGAS": "NG=F",
    "PAXG": "PAXG-USD",
    "XAG": "SI=F",
    "XAU": "GC=F",
    "XAUT": "XAUT-USD",
    "XPD": "PA=F",
    "XPT": "PL=F",
    "STXSTOCK": "STX",
}


def resolve_yfinance_symbol(ticker: str,
                            symbol_info: dict[str, Any] | None = None) -> str:
    """Resolve a Bitget trade-pool ticker to the yfinance market-data symbol."""
    base = normalize_ticker(ticker)
    if symbol_info:
        configured = symbol_info.get("yfinanceSymbol") or symbol_info.get("yfinance_symbol")
        if configured:
            return normalize_ticker(configured)
    return YFINANCE_SYMBOL_OVERRIDES.get(base, base)


def _history_window(days: int) -> tuple[str, str]:
    """Return a calendar window wide enough to contain `days` daily bars."""
    now = datetime.now(timezone.utc)
    calendar_days = max(int(days * 2.2) + 30, days + 90, 180)
    start = now - timedelta(days=calendar_days)
    end = now + timedelta(days=1)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _timestamp_ms(value: Any) -> int:
    ts = pd.to_datetime(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize(timezone.utc)
    else:
        ts = ts.tz_convert(timezone.utc)
    return int(ts.timestamp() * 1000)


def _frame_to_candles(price_frame: pd.DataFrame, yf_symbol: str,
                      days: int) -> list[dict]:
    if price_frame.empty:
        return []

    df = price_frame.copy()
    df["ticker"] = df["ticker"].astype(str).map(normalize_ticker)
    df = df[df["ticker"] == normalize_ticker(yf_symbol)].copy()
    if df.empty:
        return []

    df["date"] = pd.to_datetime(df["date"])
    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["date", "open", "high", "low", "close", "volume"])
    df = df[
        (df["open"] > 0)
        & (df["high"] > 0)
        & (df["low"] > 0)
        & (df["close"] > 0)
        & (df["high"] >= df[["open", "close"]].max(axis=1))
        & (df["low"] <= df[["open", "close"]].min(axis=1))
        & (df["volume"] >= 0)
    ]
    df = df.sort_values("date").tail(days)

    candles = []
    for row in df.to_dict("records"):
        close = float(row["close"])
        volume = float(row["volume"])
        candles.append({
            "timestamp": _timestamp_ms(row["date"]),
            "date": pd.to_datetime(row["date"]).strftime("%Y-%m-%d"),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": close,
            "volume": volume,
            "quote_volume": close * volume,
        })
    return candles


def fetch_yfinance_candles(ticker: str, days: int = 90,
                           symbol_info: dict[str, Any] | None = None,
                           use_cache: bool = True) -> tuple[str, list[dict]]:
    """Fetch daily candles from yfinance for a Bitget trade-pool ticker."""
    yf_symbol = resolve_yfinance_symbol(ticker, symbol_info)
    start, end = _history_window(days)
    prices = fetch_yfinance_ohlcv(
        [yf_symbol],
        start=start,
        end=end,
        interval="1d",
        chunk_size=1,
        retries=2,
        retry_sleep=1.0,
        use_cache=use_cache,
    )
    candles = _frame_to_candles(prices, yf_symbol, days)
    return yf_symbol, candles


def build_report(ticker: str, symbol_info: dict, yf_symbol: str,
                 candles: list[dict], requested_days: int = 0) -> dict:
    """构建输出报告."""
    report = {
        "status": "success",
        "ticker": ticker,
        "symbol": yf_symbol,
        "market_data_symbol": yf_symbol,
        "trade_symbol": symbol_info["symbol"],
        "group": symbol_info["group"],
        "source": "yfinance",
        "trade_pool_source": "bitget",
        "data_points": len(candles),
        "requested_days": requested_days,
        "partial": bool(requested_days and len(candles) < requested_days),
    }

    if candles:
        latest = candles[-1]
        report["date_range"] = {
            "from": candles[0]["date"],
            "to": latest["date"],
        }
        report["latest"] = {
            "date": latest["date"],
            "open": latest["open"],
            "high": latest["high"],
            "low": latest["low"],
            "close": latest["close"],
            "volume": latest["volume"],
        }
    else:
        report["date_range"] = None
        report["latest"] = None

    report["candles"] = candles
    return report


def get_candle_data(ticker: str, days: int = 90) -> dict:
    """获取指定品种的 yfinance 日K数据，返回完整报告字典.

    Ticker 必须存在于 Bitget RWA 交易池；Bitget 只用于确认交易池资格。
    """
    ticker = normalize_ticker(ticker)
    symbol_info = lookup_symbol(ticker)
    if symbol_info is None:
        raise ValidationError(
            f"品种 '{ticker}' 不在 Bitget RWA 合约列表中，无法交易。"
            f" 使用 'uv run trading-agent sync --quiet' 查看可用品种。"
        )

    yf_symbol, candles = fetch_yfinance_candles(
        ticker,
        days=days,
        symbol_info=symbol_info,
    )

    if not candles:
        raise DataError(
            f"品种 '{ticker}' 的 yfinance 行情为空 "
            f"(market_data_symbol={yf_symbol})。"
        )

    return build_report(
        ticker,
        symbol_info,
        yf_symbol,
        candles,
        requested_days=days,
    )


def main():
    parser = argparse.ArgumentParser(
        description="获取 Bitget 交易池品种的 yfinance 日K线数据"
    )
    parser.add_argument("ticker", help="品种代码 (如 NVDA, AAPL, XAU)")
    parser.add_argument("--days", type=int, default=90,
                        help="获取天数 (默认: 90)")
    parser.add_argument("--no-candles", action="store_true",
                        help="不输出完整 K 线数组 (仅输出摘要)")
    args = parser.parse_args()

    ticker = args.ticker.upper()

    try:
        report = get_candle_data(ticker, days=args.days)
    except (ValidationError, DataError) as e:
        print(json.dumps({"status": "error", "ticker": ticker, "message": str(e)},
                         ensure_ascii=False))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"status": "error", "ticker": ticker,
                          "message": f"数据获取失败: {e}"},
                         ensure_ascii=False))
        sys.exit(1)

    if args.no_candles:
        report.pop("candles", None)

    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
