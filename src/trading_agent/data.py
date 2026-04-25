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
        except Exception as e:
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
                 requested_days: int = 0) -> dict:
    """构建输出报告"""
    report = {
        "status": "success",
        "ticker": ticker,
        "symbol": symbol_info["symbol"],
        "group": symbol_info["group"],
        "source": "bitget",
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
    # 品种校验
    symbol_info = lookup_symbol(ticker)
    if symbol_info is None:
        raise ValidationError(
            f"品种 '{ticker}' 不在 Bitget RWA 合约列表中，无法交易。"
            f" 使用 'uv run trading-agent sync --quiet' 查看可用品种。"
        )

    # 获取数据
    symbol = symbol_info["symbol"]
    candles = fetch_all_candles(symbol, days=days)

    if not candles:
        raise DataError(f"品种 '{ticker}' ({symbol}) 未获取到任何 K 线数据。")

    return build_report(ticker, symbol_info, candles, requested_days=days)


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
