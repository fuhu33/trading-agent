"""Logic-strength scoring.

The logic engine turns fundamentals plus optional trend confirmation into a
stable 0-100 score and a history-aware trend label.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .history import append_logic_snapshot, get_recent_snapshots, infer_logic_trend


FACTOR_WEIGHTS = {
    "earnings_delta": 35,
    "sector_theme": 20,
    "expectation_revision": 20,
    "catalyst": 15,
    "price_confirmation": 10,
}


def _as_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "pass", "passed"}
    return bool(value)


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def _grade(score: float) -> str:
    if score >= 75:
        return "very_strong"
    if score >= 60:
        return "strong"
    if score >= 45:
        return "moderate"
    return "weak"


def _score_earnings(earnings: dict | None) -> tuple[int, list[str], list[str], int]:
    drivers: list[str] = []
    weaknesses: list[str] = []
    if not isinstance(earnings, dict):
        return 0, drivers, ["无可用业绩增量数据"], 0

    surprise = _as_float(earnings.get("eps_surprise_pct"), default=None)
    if surprise is None:
        return 0, drivers, ["EPS surprise 缺失"], 10

    if surprise >= 10:
        score = 35
        drivers.append(f"EPS 超预期 +{surprise:.1f}%")
    elif surprise >= 5:
        score = 28
        drivers.append(f"EPS 明显超预期 +{surprise:.1f}%")
    elif surprise >= 0:
        score = 20
        drivers.append(f"EPS 小幅超预期 +{surprise:.1f}%")
    elif surprise >= -5:
        score = 8
        weaknesses.append(f"EPS 略低于预期 {surprise:.1f}%")
    else:
        score = 0
        weaknesses.append(f"EPS 大幅 miss {surprise:.1f}%")

    return score, drivers, weaknesses, FACTOR_WEIGHTS["earnings_delta"]


def _score_sector(sector: dict | None) -> tuple[int, list[str], list[str], int]:
    drivers: list[str] = []
    weaknesses: list[str] = []
    if not isinstance(sector, dict):
        return 0, drivers, ["行业/主题景气数据缺失"], 0

    trend = str(sector.get("trend") or "").lower()
    change_20d = _as_float(sector.get("change_20d"), default=0.0) or 0.0
    etf = sector.get("etf", "sector ETF")

    if trend == "bullish" and change_20d >= 5:
        score = 20
        drivers.append(f"{etf} 20d {change_20d:+.1f}%，行业强共振")
    elif trend == "bullish":
        score = 16
        drivers.append(f"{etf} 行业趋势多头")
    elif trend == "mixed":
        score = 10
        weaknesses.append(f"{etf} 行业趋势震荡")
    elif trend == "bearish":
        score = 0
        weaknesses.append(f"{etf} 20d {change_20d:+.1f}%，行业逆风")
    else:
        score = 5
        weaknesses.append("行业趋势状态不明确")

    return score, drivers, weaknesses, FACTOR_WEIGHTS["sector_theme"]


def _score_expectation(analysts: dict | None) -> tuple[int, list[str], list[str], int]:
    drivers: list[str] = []
    weaknesses: list[str] = []
    if not isinstance(analysts, dict):
        return 0, drivers, ["机构预期数据缺失"], 0

    rating_score = _as_float(analysts.get("rating_score"), default=None)
    upside = _as_float(analysts.get("upside_pct"), default=None)

    score = 0
    if rating_score is not None:
        rating = analysts.get("rating", "rating")
        if rating_score < 2.0:
            score += 10
            drivers.append(f"分析师评级 {rating}，均值 {rating_score:.1f}")
        elif rating_score < 2.5:
            score += 7
            drivers.append(f"分析师评级偏多，均值 {rating_score:.1f}")
        elif rating_score < 3.0:
            score += 4
        elif rating_score >= 3.5:
            weaknesses.append(f"分析师评级偏弱，均值 {rating_score:.1f}")
    else:
        weaknesses.append("分析师评级均值缺失")

    if upside is not None:
        if upside >= 20:
            score += 10
            drivers.append(f"目标价空间 +{upside:.1f}%")
        elif upside >= 10:
            score += 8
            drivers.append(f"目标价仍有 +{upside:.1f}% 空间")
        elif upside >= 0:
            score += 5
        else:
            weaknesses.append(f"已超分析师均值目标价 ({upside:+.1f}%)")
    else:
        weaknesses.append("目标价空间缺失")

    return min(score, 20), drivers, weaknesses, FACTOR_WEIGHTS["expectation_revision"]


def _score_catalyst(
    next_earnings: dict | None,
    narrative: dict | None,
) -> tuple[int, list[str], list[str], int]:
    drivers: list[str] = []
    weaknesses: list[str] = []
    narrative = narrative if isinstance(narrative, dict) else {}
    earnings_catalyst = _as_bool(narrative.get("earnings_catalyst"))
    narrative_score = _as_float(narrative.get("score"), default=0.0) or 0.0

    if earnings_catalyst:
        days = next_earnings.get("days_until") if isinstance(next_earnings, dict) else None
        drivers.append(f"财报催化剂窗口，{days} 天后财报" if days is not None else "财报催化剂窗口")
        return 15, drivers, weaknesses, FACTOR_WEIGHTS["catalyst"]

    if isinstance(next_earnings, dict) and _as_bool(next_earnings.get("in_window")):
        days = next_earnings.get("days_until")
        if narrative_score >= 4:
            weaknesses.append(f"财报 {days} 天后，叙事中性需控制仓位")
            return 8, drivers, weaknesses, FACTOR_WEIGHTS["catalyst"]
        weaknesses.append(f"财报 {days} 天后但逻辑偏弱")
        return 0, drivers, weaknesses, FACTOR_WEIGHTS["catalyst"]

    if isinstance(next_earnings, dict) and next_earnings.get("days_until") is not None:
        days_until = _as_float(next_earnings.get("days_until"), default=None)
        if days_until is not None and days_until <= 30:
            drivers.append(f"下次财报 {days_until:.0f} 天后")
            return 5, drivers, weaknesses, FACTOR_WEIGHTS["catalyst"]

    return 0, drivers, weaknesses, 5


def _score_price_confirmation(trend_report: dict | None) -> tuple[int, list[str], list[str], int]:
    drivers: list[str] = []
    weaknesses: list[str] = []
    if not isinstance(trend_report, dict):
        return 0, drivers, ["缺少价格验证数据"], 0

    gate = trend_report.get("gate", {})
    trend = trend_report.get("trend", {})
    continuation = trend_report.get("continuation", {})
    gate_pass = _as_bool(gate.get("pass")) if isinstance(gate, dict) else False
    direction = str(trend.get("direction") or "").lower() if isinstance(trend, dict) else ""
    verdict = str(continuation.get("verdict") or "").lower() if isinstance(continuation, dict) else ""

    if gate_pass and verdict == "strong":
        drivers.append("价格验证逻辑: Gate PASS 且延续动力 strong")
        return 10, drivers, weaknesses, FACTOR_WEIGHTS["price_confirmation"]
    if gate_pass:
        drivers.append("价格验证逻辑: Gate PASS")
        return 7, drivers, weaknesses, FACTOR_WEIGHTS["price_confirmation"]
    if direction == "bullish":
        drivers.append("价格处于多头结构，但 Gate 尚未通过")
        return 5, drivers, weaknesses, FACTOR_WEIGHTS["price_confirmation"]

    weaknesses.append("价格尚未验证逻辑")
    return 0, drivers, weaknesses, FACTOR_WEIGHTS["price_confirmation"]


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def build_logic_report(
    ticker: str,
    fundamentals_report: dict,
    trend_report: dict | None = None,
    save_history: bool = False,
    history_path: str | Path | None = None,
) -> dict:
    """Build a LogicReport from fundamentals and optional trend data."""
    ticker = ticker.upper()

    if fundamentals_report.get("status") == "error":
        return {
            "status": "error",
            "ticker": ticker,
            "message": fundamentals_report.get("message", "fundamentals error"),
        }

    earnings = fundamentals_report.get("earnings")
    sector = fundamentals_report.get("sector")
    analysts = fundamentals_report.get("analysts")
    next_earnings = fundamentals_report.get("next_earnings")
    narrative = fundamentals_report.get("narrative")

    factor_scores: dict[str, int] = {}
    drivers: list[str] = []
    weaknesses: list[str] = []
    available_weight = 0

    scorers = {
        "earnings_delta": _score_earnings(earnings),
        "sector_theme": _score_sector(sector),
        "expectation_revision": _score_expectation(analysts),
        "catalyst": _score_catalyst(next_earnings, narrative),
        "price_confirmation": _score_price_confirmation(trend_report),
    }

    for name, (score, ds, ws, weight) in scorers.items():
        factor_scores[name] = int(score)
        drivers.extend(ds)
        weaknesses.extend(ws)
        available_weight += weight

    score_total = _clamp(sum(factor_scores.values()))
    confidence = round(max(0.0, min(1.0, available_weight / sum(FACTOR_WEIGHTS.values()))), 2)

    previous_snapshots = get_recent_snapshots(ticker, limit=3, history_path=history_path)
    trend_info = infer_logic_trend(score_total, previous_snapshots)

    logic = {
        "score": int(round(score_total)),
        "grade": _grade(score_total),
        "trend": trend_info["trend"],
        "delta": trend_info["delta"],
        "previous_score": trend_info["previous_score"],
        "confidence": confidence,
        "drivers": _dedupe(drivers + (narrative or {}).get("drivers", []))
        if isinstance(narrative, dict)
        else _dedupe(drivers),
        "weaknesses": _dedupe(weaknesses + (narrative or {}).get("concerns", []))
        if isinstance(narrative, dict)
        else _dedupe(weaknesses),
        "factor_scores": factor_scores,
    }

    report = {
        "status": "success",
        "ticker": ticker,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "logic": logic,
    }

    if save_history:
        append_logic_snapshot(ticker, report, history_path=history_path)

    return report
