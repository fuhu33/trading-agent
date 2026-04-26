"""Unit tests for the decision engine."""

from trading_agent.decision import build_decision_report


def _trend(
    *,
    gate_pass=True,
    stage="mid",
    ideal_entry=True,
    continuation="strong",
    rsi=55.0,
    direction="bullish",
):
    return {
        "status": "success",
        "ticker": "NVDA",
        "trend": {
            "direction": direction,
            "strength": "strong",
            "adx": 30.0,
        },
        "fish_body": {
            "stage": stage,
            "trend_age_days": 12,
            "cumulative_pct": 10.0,
            "deviation_pct": 3.0,
            "ideal_entry": ideal_entry,
        },
        "continuation": {
            "verdict": continuation,
            "risk_flags": ["rsi_overbought"] if rsi > 70 else [],
        },
        "gate": {
            "pass": gate_pass,
            "reason": "ADX=30 >= 20, direction=bullish"
            if gate_pass
            else "direction=neutral",
        },
        "raw": {"rsi": rsi},
    }


def _logic(score=70, grade="strong", trend="stable"):
    return {
        "logic": {
            "score": score,
            "grade": grade,
            "trend": trend,
            "drivers": ["earnings growth"],
            "weaknesses": [],
        }
    }


def _fundamentals(*, thesis="moderate", in_window=True, upside_pct=10.0):
    return {
        "status": "success",
        "ticker": "NVDA",
        "next_earnings": {"in_window": in_window, "days_until": 5},
        "analysts": {"upside_pct": upside_pct},
        "narrative": {
            "thesis": thesis,
            "earnings_catalyst": thesis == "strong" and in_window,
        },
    }


def test_gate_fail_goes_to_watch_without_entry():
    result = build_decision_report(
        "NVDA",
        _trend(gate_pass=False, direction="neutral"),
        _logic(score=75),
    )

    assert result["action"] == "watch"
    assert result["entry_allowed"] is False
    assert result["position_multiplier"] == 0
    assert "Gate FAIL" in result["reasons"][0]
    assert "Gate FAIL" in result["exit_signals"]


def test_strong_logic_enters_with_early_ideal_strong_multiplier():
    result = build_decision_report(
        "nvda",
        _trend(stage="early", ideal_entry=True, continuation="strong"),
        _logic(score=72, grade="strong", trend="stable"),
    )

    assert result["ticker"] == "NVDA"
    assert result["action"] == "enter"
    assert result["entry_allowed"] is True
    assert result["position_multiplier"] == 1.5
    assert result["final_risk_pct"] == 0.03
    assert result["final_risk_amount"] == 3000.0


def test_score_50_to_59_small_enters_with_score_discount():
    result = build_decision_report(
        "AAPL",
        _trend(stage="mid", ideal_entry=True, continuation="moderate"),
        _logic(score=55, grade="strong", trend="stable"),
    )

    assert result["action"] == "small_enter"
    assert result["entry_allowed"] is True
    assert result["position_multiplier"] == 0.5
    assert result["final_risk_pct"] == 0.01
    assert result["adjustments"][0]["name"] == "logic_moderate_or_score_below_60"


def test_logic_weakening_watches_without_new_entry():
    result = build_decision_report(
        "MSFT",
        _trend(stage="early", ideal_entry=True, continuation="strong"),
        _logic(score=80, grade="strong", trend="weakening"),
    )

    assert result["action"] == "watch"
    assert result["entry_allowed"] is False
    assert result["position_multiplier"] == 0
    assert "logic.trend weakening" in result["exit_signals"]


def test_late_stage_with_weakening_continuation_rejects():
    result = build_decision_report(
        "MU",
        _trend(stage="late", ideal_entry=False, continuation="weakening"),
        _logic(score=82, grade="strong", trend="stable"),
    )

    assert result["action"] == "reject"
    assert result["entry_allowed"] is False
    assert result["position_multiplier"] == 0
    assert "continuation weakening" in result["exit_signals"]
    assert any("rejects new entry" in reason for reason in result["reasons"])


def test_adjustment_factors_stack_on_late_overbought_position():
    result = build_decision_report(
        "MU",
        _trend(stage="late", ideal_entry=False, continuation="strong", rsi=78),
        _logic(score=62, grade="moderate", trend="stable"),
        _fundamentals(thesis="moderate", in_window=True, upside_pct=-5.0),
    )

    assert result["action"] == "enter"
    assert result["entry_allowed"] is True
    # Base late/strong multiplier is 0.4. Moderate logic first discounts to
    # the 0.3 floor, then neutral earnings, late RSI, and analyst penalties apply.
    assert result["position_multiplier"] == 0.1029
    assert result["final_risk_pct"] == 0.002058
    assert [adj["name"] for adj in result["adjustments"]] == [
        "logic_moderate_or_score_below_60",
        "neutral_earnings_window",
        "late_rsi_overbought",
        "negative_analyst_upside",
    ]


def test_position_matrix_mid_nonideal_moderate():
    result = build_decision_report(
        "COST",
        _trend(stage="mid", ideal_entry=False, continuation="moderate"),
        _logic(score=68, grade="strong", trend="stable"),
    )

    assert result["action"] == "enter"
    assert result["position_multiplier"] == 0.4
    assert result["final_risk_pct"] == 0.008
