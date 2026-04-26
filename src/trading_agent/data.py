"""Bitget 日K数据获取

从 Bitget API 获取指定品种的日K线历史数据 (OHLCV)。
仅限 Bitget 已上线的 RWA 合约品种。

用法 (CLI):
    uv run trading-agent data NVDA            # 获取 NVDA 最近 90 天日K
    uv run trading-agent data AAPL --days 60  # 获取 AAPL 最近 60 天日K
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone

import yfinance as yf
try:
    from curl_cffi import requests as _curl_requests
    _YF_SESSION = _curl_requests.Session(impersonate="chrome")
except Exception:
    _YF_SESSION = None

from .exceptions import DataError, ValidationError
from .symbols import lookup_symbol
from .utils import make_request

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

API_BASE = "https://api.bitget.com"
CANDLES_ENDPOINT = "/api/v2/mix/market/history-candles"
MAX_CANDLES_PER_REQUEST = 200  # Bitget API 单次最多返回 200 条
REQUEST_TIMEOUT = 15


# ---------------------------------------------------------------------------
# 核心逻辑
# ---------------------------------------------------------------------------

def fetch_candles_page(symbol: str, granularity: str = "1D",
                       end_time: int | None = None,
                       limit: int = MAX_CANDLES_PER_REQUEST) -> list[list]:
    """获取单页 K 线数据

    返回值: [[timestamp, open, high, low, close, volume_base, volume_quote], ...]
    按时间从新到旧排列 (Bitget 默认)
    """
    params = {
        "symbol": symbol,
        "productType": "USDT-FUTURES",
        "granularity": granularity,
        "limit": str(limit),
    }
    if end_time is not None:
        params["endTime"] = str(end_time)

    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{API_BASE}{CANDLES_ENDPOINT}?{query}"

    data = make_request(url, timeout=REQUEST_TIMEOUT)

    if data.get("code") != "00000":
        raise DataError(f"API 返回错误: {data.get('msg', 'unknown')}")

    return data.get("data", [])


def fetch_all_candles(symbol: str, days: int = 90) -> list[dict]:
    """获取指定天数的全部日K数据，自动分页拼接

    返回值: 按时间从旧到新排列的 OHLCV 字典列表
    """
    all_candles = []
    end_time = None
    seen_timestamps = set()

    while len(all_candles) < days:
        remaining = days - len(all_candles)
        limit = min(remaining, MAX_CANDLES_PER_REQUEST)

        try:
            page = fetch_candles_page(symbol, end_time=end_time, limit=limit)
        except Exception:
            if not all_candles:
                raise
            # 已有部分数据，分页获取失败时停止
            break

        if not page:
            break

        new_count = 0
        for candle in page:
            ts = int(candle[0])
            if ts in seen_timestamps:
                continue
            seen_timestamps.add(ts)
            all_candles.append(candle)
            new_count += 1

        if new_count == 0:
            break

        # 下一页: 用当前页最早的时间戳作为 endTime
        earliest_ts = min(int(c[0]) for c in page)
        end_time = earliest_ts - 1  # 减 1ms 避免重复

        # 请求间隔，避免限流
        time.sleep(0.3)

    # 转为字典并按时间升序排列
    result = []
    for c in all_candles:
        ts_ms = int(c[0])
        result.append({
            "timestamp": ts_ms,
            "date": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d"),
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4]),
            "volume": float(c[5]),
            "quote_volume": float(c[6]),
        })

    result.sort(key=lambda x: x["timestamp"])
    return result


def build_report(ticker: str, symbol_info: dict, candles: list[dict],
                 requested_days: int = 0, source: str = "bitget",
                 tradable_on_bitget: bool = True,
                 bitget_symbol: str | None = None) -> dict:
    """构建输出报告"""
    report = {
        "status": "success",
        "ticker": ticker,
        "symbol": symbol_info["symbol"],
        "group": symbol_info["group"],
        "source": source,
        "analysis_source": source,
        "tradable_on_bitget": tradable_on_bitget,
        "bitget_symbol": bitget_symbol,
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


def _coerce_yfinance_date(value) -> str:
    """将 yfinance 返回的日期索引/字段转成 YYYY-MM-DD。"""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def fetch_yfinance_candles(ticker: str, days: int = 90) -> list[dict]:
    """用 yfinance 获取任意美股现货日 K，返回统一 OHLCV 格式。"""
    period = f"{max(days, 1)}d"
    try:
        yf_obj = yf.Ticker(ticker, session=_YF_SESSION)
        hist = yf_obj.history(period=period, interval="1d", auto_adjust=False)
    except Exception as e:
        raise DataError(f"yfinance 获取 '{ticker}' 日K失败: {e}") from e

    if hist is None or getattr(hist, "empty", False):
        raise DataError(f"yfinance 未获取到 '{ticker}' 日K数据。")

    rows = []
    try:
        iterable = hist.reset_index().iterrows()
    except Exception as e:
        raise DataError(f"yfinance 日K格式异常: {e}") from e

    for _, row in iterable:
        try:
            date_value = row.get("Date") or row.get("Datetime")
            date_str = _coerce_yfinance_date(date_value)
            dt = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
            rows.append({
                "timestamp": int(dt.timestamp() * 1000),
                "date": date_str,
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row.get("Volume", 0) or 0),
                "quote_volume": float(row.get("Volume", 0) or 0) * float(row["Close"]),
            })
        except Exception:
            continue

    rows.sort(key=lambda x: x["timestamp"])
    return rows[-days:]


# ---------------------------------------------------------------------------
# 公开接口 (供其他模块调用)
# ---------------------------------------------------------------------------

def get_candle_data(ticker: str, days: int = 90) -> dict:
    """获取指定品种的日K数据，返回完整报告字典

    Args:
        ticker: 品种代码 (如 NVDA, AAPL, XAU)
        days: 获取天数 (默认 90)

    Returns:
        包含 status, candles 等字段的报告字典

    Raises:
        ValidationError: ticker 不在 Bitget 品种列表中
        DataError: 数据获取失败
    """
    # 数据源策略：美股/ETF 用 yfinance 做主分析源；Bitget 仅保留可交易性与合约映射。
    # 商品仍用 Bitget，避免 XAU/NATGAS 等 ticker 在 yfinance 上存在映射歧义。
    symbol_info = lookup_symbol(ticker)
    group = symbol_info.get("group") if symbol_info else "us_stock"
    bitget_symbol = symbol_info.get("symbol") if symbol_info else None
    tradable_on_bitget = symbol_info is not None

    if group in ("stock", "etf", "us_stock"):
        candles = fetch_yfinance_candles(ticker, days=days)
        if not candles:
            raise DataError(f"品种 '{ticker}' 未获取到任何 yfinance 日K数据。")
        return build_report(
            ticker,
            {"symbol": ticker, "group": group},
            candles,
            requested_days=days,
            source="yfinance",
            tradable_on_bitget=tradable_on_bitget,
            bitget_symbol=bitget_symbol,
        )

    if symbol_info is not None:
        symbol = symbol_info["symbol"]
        candles = fetch_all_candles(symbol, days=days)
        if not candles:
            raise DataError(f"品种 '{ticker}' ({symbol}) 未获取到任何 K 线数据。")
        return build_report(
            ticker,
            symbol_info,
            candles,
            requested_days=days,
            source="bitget",
            tradable_on_bitget=True,
            bitget_symbol=symbol,
        )

    raise ValidationError(
        f"品种 '{ticker}' 不在 Bitget RWA 商品列表中，且无法按普通美股/ETF 使用 yfinance 解析。"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="获取 Bitget RWA 品种日K线数据"
    )
    parser.add_argument("ticker", help="品种代码 (如 NVDA, AAPL, XAU)")
    parser.add_argument("--days", type=int, default=90,
                        help="获取天数 (默认: 90, 最大约 90)")
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
