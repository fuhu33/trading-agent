"""Decision engine for turning trend and logic reports into a trade plan.

The module is intentionally pure: callers pass already-built reports and the
function returns a structured DecisionReport without fetching data.
"""

from datetime import datetime, timezone
from typing import Any


ACTION_LABELS = {
    "enter": "Enter",
    "small_enter": "Small enter",
    "watch": "Watch",
    "hold": "Hold",
    "reduce": "Reduce",
    "exit": "Exit",
    "reject": "Reject",
}


def _as_float(value: Any, default: float = 0.0) -> float:
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
        return value.strip().lower() in {"true", "pass", "passed", "yes", "1"}
    return bool(value)


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _logic_section(logic_report: dict | None) -> dict:
    if not isinstance(logic_report, dict):
        return {}
    logic = logic_report.get("logic")
    return logic if isinstance(logic, dict) else logic_report


def _gate_pass(trend_report: dict | None) -> bool:
    if not isinstance(trend_report, dict):
        return False
    gate = trend_report.get("gate")
    if isinstance(gate, dict) and "pass" in gate:
        return _as_bool(gate.get("pass"))
    return _as_bool(trend_report.get("gate_pass", False))


def _gate_reason(trend_report: dict | None) -> str:
    if not isinstance(trend_report, dict):
        return "trend_report missing"
    gate = trend_report.get("gate")
    if isinstance(gate, dict):
        return str(gate.get("reason") or "")
    return str(trend_report.get("gate_reason") or "")


def _position_multiplier(stage: str, ideal_entry: bool, continuation: str) -> float:
    """Return the base position multiplier from the fish-body matrix."""
    if continuation == "weakening":
        return 0.0 if stage == "late" else 0.3

    if stage == "early":
        if continuation == "strong":
            return 1.5 if ideal_entry else 1.0
        if continuation == "moderate":
            return 1.0 if ideal_entry else 0.6

    if stage == "mid":
        if ideal_entry and continuation == "strong":
            return 1.2
        if ideal_entry and continuation == "moderate":
            return 1.0
        if not ideal_entry and continuation == "strong":
            return 0.6
        if not ideal_entry and continuation == "moderate":
            return 0.4

    if stage == "late":
        if continuation == "strong":
            return 0.4
        if continuation == "moderate":
            return 0.3

    return 0.0


def _earnings_window_neutral(fundamentals_report: dict | None) -> bool:
    if not isinstance(fundamentals_report, dict):
        return False

    next_earnings = fundamentals_report.get("next_earnings")
    if not isinstance(next_earnings, dict) or not _as_bool(next_earnings.get("in_window")):
        return False

    narrative = fundamentals_report.get("narrative")
    thesis = ""
    earnings_catalyst = False
    if isinstance(narrative, dict):
        thesis = str(narrative.get("thesis") or "").lower()
        earnings_catalyst = _as_bool(narrative.get("earnings_catalyst"))

    return thesis in {"neutral", "moderate"} and not earnings_catalyst


def _negative_analyst_upside(fundamentals_report: dict | None) -> bool:
    if not isinstance(fundamentals_report, dict):
        return False
    analysts = fundamentals_report.get("analysts")
    if not isinstance(analysts, dict):
        return False
    return _as_float(analysts.get("upside_pct"), default=0.0) < 0


def _rsi_overbought_late(trend_report: dict | None, stage: str) -> bool:
    if stage != "late" or not isinstance(trend_report, dict):
        return False

    continuation = trend_report.get("continuation")
    if isinstance(continuation, dict):
        if "rsi_overbought" in _as_list(continuation.get("risk_flags")):
            return True

    raw = trend_report.get("raw")
    if isinstance(raw, dict):
        return _as_float(raw.get("rsi"), default=0.0) > 70
    return False


def _apply_adjustments(
    multiplier: float,
    logic_score: float,
    logic_grade: str,
    trend_report: dict | None,
    fundamentals_report: dict | None,
    stage: str,
) -> tuple[float, list[dict]]:
    adjustments: list[dict] = []

    if multiplier <= 0:
        return 0.0, adjustments

    if logic_grade == "moderate" or logic_score < 60:
        before = multiplier
        multiplier *= 0.5
        if before > 0:
            multiplier = max(multiplier, 0.3)
        adjustments.append({
            "name": "logic_moderate_or_score_below_60",
            "factor": 0.5,
            "reason": "logic grade is moderate or score is below 60",
        })

    if _earnings_window_neutral(fundamentals_report):
        multiplier *= 0.7
        adjustments.append({
            "name": "neutral_earnings_window",
            "factor": 0.7,
            "reason": "neutral earnings window without a strong catalyst",
        })

    if _rsi_overbought_late(trend_report, stage):
        multiplier *= 0.7
        adjustments.append({
            "name": "late_rsi_overbought",
            "factor": 0.7,
            "reason": "RSI is overbought in a late trend stage",
        })

    if _negative_analyst_upside(fundamentals_report):
        multiplier *= 0.7
        adjustments.append({
            "name": "negative_analyst_upside",
            "factor": 0.7,
            "reason": "analyst upside is below zero",
        })

    return multiplier, adjustments


def build_decision_report(
    ticker: str,
    trend_report: dict,
    logic_report: dict,
    fundamentals_report: dict | None = None,
    account: float = 100000,
    risk_pct: float = 0.02,
) -> dict:
    """Build a DecisionReport from trend, logic, and optional fundamentals.

    Args:
        ticker: Ticker symbol.
        trend_report: TrendReport from trend.py.
        logic_report: LogicReport. Supports either {"logic": {...}} or direct
            fields such as {"score": 70, "grade": "strong"}.
        fundamentals_report: Optional fundamentals report for adjustment factors.
        account: Account equity used to show final risk amount.
        risk_pct: Base risk percentage before position multipliers.

    Returns:
        DecisionReport dictionary.
    """
    logic = _logic_section(logic_report)
    logic_score = _as_float(logic.get("score"), default=0.0)
    logic_grade = str(logic.get("grade") or "").lower()
    logic_trend = str(logic.get("trend") or "unknown").lower()
    logic_drivers = _as_list(logic.get("drivers"))
    logic_weaknesses = _as_list(logic.get("weaknesses"))

    fish_body = trend_report.get("fish_body", {}) if isinstance(trend_report, dict) else {}
    continuation_report = trend_report.get("continuation", {}) if isinstance(trend_report, dict) else {}
    trend = trend_report.get("trend", {}) if isinstance(trend_report, dict) else {}

    stage = str(fish_body.get("stage") or "n/a").lower() if isinstance(fish_body, dict) else "n/a"
    ideal_entry = _as_bool(fish_body.get("ideal_entry")) if isinstance(fish_body, dict) else False
    continuation = (
        str(continuation_report.get("verdict") or "unknown").lower()
        if isinstance(continuation_report, dict)
        else "unknown"
    )
    trend_direction = (
        str(trend.get("direction") or "unknown").lower()
        if isinstance(trend, dict)
        else "unknown"
    )
    gate_pass = _gate_pass(trend_report)
    gate_reason = _gate_reason(trend_report)

    reasons: list[str] = []
    exit_signals: list[str] = []

    if gate_pass:
        reasons.append("Gate PASS")
    else:
        reasons.append(f"Gate FAIL: {gate_reason}" if gate_reason else "Gate FAIL")
        exit_signals.append("Gate FAIL")

    reasons.append(f"logic.score={logic_score:g}, logic.trend={logic_trend}")
    reasons.append(
        f"fish_body.stage={stage}, ideal_entry={ideal_entry}, continuation={continuation}"
    )

    if logic_drivers:
        reasons.append("drivers: " + "; ".join(str(item) for item in logic_drivers))
    if logic_weaknesses:
        reasons.append("weaknesses: " + "; ".join(str(item) for item in logic_weaknesses))

    if logic_trend == "weakening":
        exit_signals.append("logic.trend weakening")
    if continuation == "weakening":
        exit_signals.append("continuation weakening")
    if stage == "late":
        exit_signals.append("fish_body late")

    if not gate_pass:
        action = "watch" if logic_score >= 50 else "reject"
        base_multiplier = 0.0
    elif stage == "late" and continuation == "weakening":
        action = "reject"
        base_multiplier = 0.0
        reasons.append("late trend with weakening continuation rejects new entry")
    elif logic_trend == "weakening":
        action = "reduce" if stage == "late" or continuation == "weakening" else "watch"
        base_multiplier = 0.0
        reasons.append("logic trend is weakening, no new entry allowed")
    elif logic_score >= 60:
        action = "enter"
        base_multiplier = _position_multiplier(stage, ideal_entry, continuation)
    elif 50 <= logic_score < 60 and logic_trend != "weakening":
        action = "small_enter"
        base_multiplier = _position_multiplier(stage, ideal_entry, continuation)
    else:
        action = "watch"
        base_multiplier = 0.0
        reasons.append("logic score below 50")

    position_multiplier, adjustments = _apply_adjustments(
        base_multiplier,
        logic_score,
        logic_grade,
        trend_report,
        fundamentals_report,
        stage,
    )

    if position_multiplier <= 0 and action in {"enter", "small_enter"}:
        action = "reject"
        reasons.append("position matrix produced zero size")

    entry_allowed = action in {"enter", "small_enter"} and position_multiplier > 0
    final_risk_pct = risk_pct * position_multiplier if entry_allowed else 0.0
    final_risk_amount = account * final_risk_pct if entry_allowed else 0.0

    return {
        "status": "success",
        "ticker": ticker.upper(),
        "action": action,
        "action_label": ACTION_LABELS[action],
        "entry_allowed": entry_allowed,
        "position_multiplier": round(position_multiplier, 4),
        "final_risk_pct": round(final_risk_pct, 6),
        "final_risk_amount": round(final_risk_amount, 2),
        "base_risk_pct": risk_pct,
        "account": round(account, 2),
        "reasons": reasons,
        "adjustments": adjustments,
        "exit_signals": exit_signals,
        "inputs": {
            "gate_pass": gate_pass,
            "gate_reason": gate_reason,
            "trend_direction": trend_direction,
            "stage": stage,
            "ideal_entry": ideal_entry,
            "continuation": continuation,
            "logic_score": logic_score,
            "logic_grade": logic_grade,
            "logic_trend": logic_trend,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
