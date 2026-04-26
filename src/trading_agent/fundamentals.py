"""基本面分析模块 (Stage 0)

通过 yfinance + Finnhub 提取 4 个核心信号:
  1. 业绩面: 最近一次财报 EPS/营收超预期幅度
  2. 预期面: 下次财报日 + 是否在 14 天分析窗口内
  3. 行业面: 所属 sector ETF 趋势 (5日/20日变化)
  4. 评级面: 分析师评级汇总 + 目标价隐含上涨空间

输出综合的 narrative_score (0-10) 与 thesis (strong/moderate/weak)。

用法 (CLI):
    uv run trading-agent fund NVDA
    uv run trading-agent fund NVDA --force   # 跳过缓存
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yfinance as yf
try:
    from curl_cffi import requests as _curl_requests
    _YF_SESSION = _curl_requests.Session(impersonate="chrome")
except Exception:
    _YF_SESSION = None  # curl_cffi 不可用时回退到 yfinance 默认 requests

from dotenv import load_dotenv

from .utils import safe_float, make_request

# 加载 .env (如果存在)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

CACHE_DIR = _PROJECT_ROOT / "config"
CACHE_FILE = CACHE_DIR / "fundamentals_cache.json"
CACHE_TTL_SECONDS = 6 * 3600  # 6 小时 (基本面变化慢)

# Keep yfinance's SQLite timezone cache inside the project. The default user
# cache path can be unwritable in sandboxed/desktop runs.
try:
    yf.set_tz_cache_location(str(CACHE_DIR / "yfinance_cache"))
except Exception:
    pass

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "").strip()
FINNHUB_BASE = "https://finnhub.io/api/v1"

EARNINGS_WINDOW_DAYS = 14  # 1-2 周波段分析窗口

# Sector → 代理 ETF 映射
SECTOR_ETF_MAP = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financial Services": "XLF",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Communication Services": "XLC",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Basic Materials": "XLB",
}

# 半导体行业额外覆盖 (industry 字段更精确)
INDUSTRY_ETF_OVERRIDE = {
    "Semiconductors": "SMH",
    "Semiconductor Equipment & Materials": "SMH",
}


# ---------------------------------------------------------------------------
# 缓存 (内存优化: 批量模式下避免重复 I/O)
# ---------------------------------------------------------------------------

_CACHE_IN_MEMORY: dict | None = None


def _load_cache_file() -> dict:
    """从文件加载缓存"""
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache_file(cache: dict) -> None:
    """保存缓存到文件"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False, default=str)


def _get_cache() -> dict:
    """获取内存缓存 (惰性加载)"""
    global _CACHE_IN_MEMORY
    if _CACHE_IN_MEMORY is None:
        _CACHE_IN_MEMORY = _load_cache_file()
    return _CACHE_IN_MEMORY


def get_cached(ticker: str) -> dict | None:
    """获取单个 ticker 的有效缓存"""
    cache = _get_cache()
    entry = cache.get(ticker)
    if not entry:
        return None
    cached_at = entry.get("_cached_at", "")
    try:
        ts = datetime.fromisoformat(cached_at)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        if age > CACHE_TTL_SECONDS:
            return None
    except (ValueError, TypeError):
        return None
    return entry.get("data")


def set_cached(ticker: str, data: dict) -> None:
    """写入内存缓存 (不立即落盘)"""
    cache = _get_cache()
    cache[ticker] = {
        "_cached_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }


def flush_cache() -> None:
    """将内存缓存写入文件 (批量扫描结束后调用)"""
    global _CACHE_IN_MEMORY
    if _CACHE_IN_MEMORY is not None:
        _save_cache_file(_CACHE_IN_MEMORY)


# ---------------------------------------------------------------------------
# yfinance 数据抓取 (单例化: 一次创建 yf.Ticker)
# ---------------------------------------------------------------------------

def _extract_info(yf_obj: yf.Ticker) -> dict:
    """从 yf.Ticker 提取基础信息"""
    try:
        info = yf_obj.info or {}
    except Exception as e:
        return {"error": f"yfinance info 获取失败: {e}"}

    return {
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "current_price": safe_float(info.get("currentPrice") or info.get("regularMarketPrice"), default=None),
        "recommendation_mean": safe_float(info.get("recommendationMean"), default=None),
        "recommendation_key": info.get("recommendationKey"),
        "target_mean": safe_float(info.get("targetMeanPrice"), default=None),
        "target_high": safe_float(info.get("targetHighPrice"), default=None),
        "target_low": safe_float(info.get("targetLowPrice"), default=None),
        "num_analysts": info.get("numberOfAnalystOpinions"),
    }


def _extract_earnings(yf_obj: yf.Ticker) -> dict | None:
    """从 yf.Ticker 提取最近一次财报 EPS 数据"""
    try:
        hist = yf_obj.earnings_history
        if hist is None or hist.empty:
            return None

        hist_with_actual = hist.dropna(subset=["epsActual"]) if "epsActual" in hist.columns else hist
        if hist_with_actual.empty:
            return None
        latest = hist_with_actual.iloc[-1]

        eps_actual = safe_float(latest.get("epsActual"), default=None)
        eps_est = safe_float(latest.get("epsEstimate"), default=None)

        surprise_pct = None
        if eps_actual is not None and eps_est is not None and eps_est != 0:
            surprise_pct = round((eps_actual - eps_est) / abs(eps_est) * 100, 2)

        report_date = None
        if hasattr(latest, "name") and latest.name:
            try:
                report_date = str(latest.name)[:10]
            except Exception:
                pass

        return {
            "last_report_date": report_date,
            "eps_actual": eps_actual,
            "eps_estimate": eps_est,
            "eps_surprise_pct": surprise_pct,
        }
    except Exception:
        return None


def _extract_next_earnings(yf_obj: yf.Ticker) -> dict | None:
    """从 yf.Ticker 提取下次财报日"""
    try:
        cal = yf_obj.calendar
        if not cal:
            return None
        ed = cal.get("Earnings Date") if isinstance(cal, dict) else None
        if not ed:
            return None
        if isinstance(ed, list):
            next_date = ed[0]
        else:
            next_date = ed

        if hasattr(next_date, "isoformat"):
            date_str = next_date.isoformat()[:10]
            today = datetime.now(timezone.utc).date()
            try:
                target = datetime.fromisoformat(date_str).date()
                days_until = (target - today).days
            except Exception:
                days_until = None
            return {
                "date": date_str,
                "days_until": days_until,
                "in_window": days_until is not None and 0 <= days_until <= EARNINGS_WINDOW_DAYS,
                "source": "yfinance",
            }
        return None
    except Exception:
        return None


def fetch_etf_trend(etf_ticker: str) -> dict | None:
    """获取 sector ETF 的 5日/20日变化"""
    if not etf_ticker:
        return None
    try:
        yf_obj = yf.Ticker(etf_ticker, session=_YF_SESSION)
        hist = yf_obj.history(period="2mo", interval="1d")
        if hist.empty or len(hist) < 21:
            return None

        latest_close = float(hist["Close"].iloc[-1])
        close_5d_ago = float(hist["Close"].iloc[-6])
        close_20d_ago = float(hist["Close"].iloc[-21])

        change_5d = round((latest_close - close_5d_ago) / close_5d_ago * 100, 2)
        change_20d = round((latest_close - close_20d_ago) / close_20d_ago * 100, 2)

        if change_5d > 0 and change_20d > 2:
            trend = "bullish"
        elif change_5d < 0 and change_20d < -2:
            trend = "bearish"
        else:
            trend = "mixed"

        return {
            "etf": etf_ticker,
            "change_5d": change_5d,
            "change_20d": change_20d,
            "trend": trend,
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Finnhub 补充 (如果配置了 Key)
# ---------------------------------------------------------------------------

def fetch_finnhub_earnings_calendar(ticker: str) -> dict | None:
    """从 Finnhub 获取财报日历 (yfinance 兜底)"""
    if not FINNHUB_API_KEY:
        return None

    today = datetime.now(timezone.utc).date()
    end = today + timedelta(days=90)
    url = (f"{FINNHUB_BASE}/calendar/earnings"
           f"?from={today.isoformat()}&to={end.isoformat()}"
           f"&symbol={ticker}&token={FINNHUB_API_KEY}")
    try:
        data = make_request(url, timeout=10)
        events = data.get("earningsCalendar", [])
        if not events:
            return None
        events.sort(key=lambda x: x.get("date", ""))
        for ev in events:
            try:
                ev_date = datetime.fromisoformat(ev["date"]).date()
                if ev_date >= today:
                    days_until = (ev_date - today).days
                    return {
                        "date": ev["date"],
                        "days_until": days_until,
                        "in_window": 0 <= days_until <= EARNINGS_WINDOW_DAYS,
                        "source": "finnhub",
                        "hour": ev.get("hour"),
                        "eps_estimate": safe_float(ev.get("epsEstimate"), default=None),
                        "revenue_estimate": safe_float(ev.get("revenueEstimate"), default=None),
                        "quarter": ev.get("quarter"),
                        "year": ev.get("year"),
                    }
            except (ValueError, KeyError):
                continue
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 综合评分
# ---------------------------------------------------------------------------

def _format_earnings_hour(hour: str | None) -> str:
    """将 Finnhub 财报时段转换为报告友好的中文标签。"""
    if not hour:
        return ""
    hour_map = {
        "bmo": "盘前",
        "amc": "盘后",
        "dmh": "盘中",
    }
    return hour_map.get(str(hour).lower(), str(hour))


def _format_earnings_source(source: str | None) -> str:
    """格式化财报日来源，便于追踪数据链路。"""
    if not source:
        return ""
    return f"[{source}]"


def compute_narrative(earnings: dict | None,
                      next_earnings: dict | None,
                      sector: dict | None,
                      analysts: dict | None) -> dict:
    """综合 4 个信号给出 narrative_score (0-10) 与 thesis 标签

    评分规则 (满分 10):
      - 业绩面 (0-3): 财报超预期幅度
      - 行业面 (0-2): sector ETF 趋势
      - 评级面 (0-3): 分析师评级 + 上涨空间
      - 预期面 (-2~+1): 财报催化剂或扣分
    """
    score = 0
    drivers = []
    concerns = []

    # --- 业绩面 (0-3) ---
    if earnings and earnings.get("eps_surprise_pct") is not None:
        sp = earnings["eps_surprise_pct"]
        if sp >= 10:
            score += 3
            drivers.append(f"EPS 超预期 +{sp:.1f}% (强劲)")
        elif sp >= 3:
            score += 2
            drivers.append(f"EPS 超预期 +{sp:.1f}%")
        elif sp >= 0:
            score += 1
            drivers.append(f"EPS 微超预期 +{sp:.1f}%")
        elif sp >= -5:
            concerns.append(f"EPS 略低于预期 {sp:.1f}%")
        else:
            score -= 1
            concerns.append(f"EPS 大幅 miss {sp:.1f}%")
    else:
        concerns.append("无可用 EPS 数据")

    # --- 行业面 (0-2) ---
    if sector and sector.get("trend"):
        if sector["trend"] == "bullish":
            score += 2
            drivers.append(f"行业 ETF {sector['etf']} 多头 (20d {sector['change_20d']:+.1f}%)")
        elif sector["trend"] == "mixed":
            score += 1
        else:
            concerns.append(f"行业 ETF {sector['etf']} 弱势 (20d {sector['change_20d']:+.1f}%)")

    # --- 评级面 (0-3) ---
    if analysts:
        rec = analysts.get("rating_score")
        upside = analysts.get("upside_pct")

        if rec is not None:
            if rec < 2.0:
                score += 2
                drivers.append(f"分析师评级: {analysts.get('rating')} (均值 {rec:.1f})")
            elif rec < 2.5:
                score += 1
            elif rec >= 3.5:
                score -= 1
                concerns.append(f"分析师评级偏空 (均值 {rec:.1f})")

        if upside is not None:
            if upside > 10:
                score += 1
                drivers.append(f"目标价隐含上涨空间 +{upside:.1f}%")
            elif upside < -5:
                score -= 1
                concerns.append(f"已超目标价 ({upside:+.1f}%)")

    # --- 预期面: 财报催化剂判定 ---
    pre_score = score
    if next_earnings and next_earnings.get("in_window"):
        days = next_earnings['days_until']
        hour_label = _format_earnings_hour(next_earnings.get("hour"))
        source_label = _format_earnings_source(next_earnings.get("source"))
        timing_text = f"{days}天后{hour_label}发财报{source_label}"
        if pre_score >= 6:
            score += 1
            drivers.append(f"财报催化剂: {timing_text}, 叙事强 -> 先手窗口")
        elif pre_score >= 4:
            concerns.append(f"财报 {timing_text}, 叙事中性 -> 小仓位试单")
        else:
            score -= 2
            concerns.append(f"财报 {timing_text}, 叙事弱 -> 回避")
    elif next_earnings and next_earnings.get("days_until") is not None:
        if next_earnings["days_until"] <= 30:
            hour_label = _format_earnings_hour(next_earnings.get("hour"))
            source_label = _format_earnings_source(next_earnings.get("source"))
            drivers.append(f"下次财报 {next_earnings['days_until']} 天后{hour_label}{source_label}")

    # 限制分数到 0-10
    score = max(0, min(10, score))

    # Thesis 标签
    if score >= 7:
        thesis = "strong"
    elif score >= 4:
        thesis = "moderate"
    else:
        thesis = "weak"

    # 财报催化剂标记
    earnings_catalyst = (
        next_earnings is not None
        and next_earnings.get("in_window", False)
        and pre_score >= 6
    )

    return {
        "score": score,
        "thesis": thesis,
        "earnings_catalyst": earnings_catalyst,
        "drivers": drivers,
        "concerns": concerns,
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

REC_KEY_MAP = {
    "strong_buy": "Strong Buy",
    "buy": "Buy",
    "hold": "Hold",
    "sell": "Sell",
    "strong_sell": "Strong Sell",
    "underperform": "Underperform",
}


def build_fundamentals_report(ticker: str, force_refresh: bool = False) -> dict:
    """完整基本面分析

    Args:
        ticker: 股票代码 (如 NVDA, AAPL)
        force_refresh: 跳过缓存

    Returns:
        基本面 JSON 报告
    """
    ticker = ticker.upper()

    # 检查缓存
    if not force_refresh:
        cached = get_cached(ticker)
        if cached is not None:
            cached["_cache_hit"] = True
            return cached

    # 统一创建 yf.Ticker (单例化, 避免 3 次实例化)
    yf_obj = yf.Ticker(ticker, session=_YF_SESSION)

    # 1. 基础信息
    info = _extract_info(yf_obj)
    if "error" in info:
        return {
            "status": "error",
            "ticker": ticker,
            "message": info["error"],
        }

    # 2. 业绩
    earnings = _extract_earnings(yf_obj)

    # 3. 下次财报 (yfinance 优先, Finnhub 兜底)
    next_earnings = _extract_next_earnings(yf_obj) or fetch_finnhub_earnings_calendar(ticker)

    # 4. 行业 ETF (industry 优先于 sector)
    industry = info.get("industry")
    sector_name = info.get("sector")
    etf_ticker = INDUSTRY_ETF_OVERRIDE.get(industry) or SECTOR_ETF_MAP.get(sector_name)
    sector_data = None
    if etf_ticker:
        etf_trend = fetch_etf_trend(etf_ticker)
        if etf_trend:
            sector_data = {
                "sector": sector_name,
                "industry": industry,
                **etf_trend,
            }

    # 5. 分析师评级
    analysts = None
    if info.get("recommendation_mean") is not None:
        upside = None
        if info.get("target_mean") and info.get("current_price"):
            upside = round((info["target_mean"] - info["current_price"]) / info["current_price"] * 100, 2)

        analysts = {
            "rating_score": info.get("recommendation_mean"),
            "rating": REC_KEY_MAP.get(info.get("recommendation_key"), info.get("recommendation_key")),
            "target_mean": info.get("target_mean"),
            "target_high": info.get("target_high"),
            "current_price": info.get("current_price"),
            "upside_pct": upside,
            "num_analysts": info.get("num_analysts"),
        }

    # 6. 综合叙事
    narrative = compute_narrative(earnings, next_earnings, sector_data, analysts)

    report = {
        "status": "success",
        "ticker": ticker,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "earnings": earnings,
        "next_earnings": next_earnings,
        "sector": sector_data,
        "analysts": analysts,
        "narrative": narrative,
    }

    # 写内存缓存
    set_cached(ticker, report)
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Stage 0 基本面分析")
    parser.add_argument("ticker", help="股票代码 (如 NVDA, AAPL)")
    parser.add_argument("--force", action="store_true", help="跳过缓存")
    args = parser.parse_args()

    try:
        report = build_fundamentals_report(args.ticker, force_refresh=args.force)
        # CLI 模式下立即落盘
        flush_cache()
    except Exception as e:
        print(json.dumps({"status": "error", "ticker": args.ticker, "message": str(e)},
                         ensure_ascii=False))
        sys.exit(1)

    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
