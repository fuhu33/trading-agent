"""logic 模块单元测试。"""

from pathlib import Path
from uuid import uuid4

from trading_agent.history import append_logic_snapshot
from trading_agent.logic import build_logic_report


def _history_path():
    root = Path(".test_artifacts")
    root.mkdir(exist_ok=True)
    return root / f"logic_history_{uuid4().hex}.json"


def _fundamentals(**overrides):
    base = {
        "status": "success",
        "ticker": "NVDA",
        "earnings": {
            "eps_surprise_pct": 12.0,
        },
        "sector": {
            "etf": "SMH",
            "trend": "bullish",
            "change_20d": 8.0,
        },
        "analysts": {
            "rating": "Buy",
            "rating_score": 1.8,
            "upside_pct": 15.0,
        },
        "next_earnings": {
            "in_window": True,
            "days_until": 6,
        },
        "narrative": {
            "score": 7,
            "thesis": "strong",
            "earnings_catalyst": True,
            "drivers": ["原始叙事驱动"],
            "concerns": [],
        },
    }
    base.update(overrides)
    return base


def _trend(**overrides):
    base = {
        "gate": {"pass": True, "reason": "ADX=30 >= 20"},
        "trend": {"direction": "bullish"},
        "continuation": {"verdict": "strong"},
    }
    base.update(overrides)
    return base


def test_build_logic_report_scores_strong_case():
    path = _history_path()
    result = build_logic_report(
        "nvda",
        _fundamentals(),
        trend_report=_trend(),
        history_path=path,
    )

    logic = result["logic"]
    assert result["ticker"] == "NVDA"
    assert logic["score"] == 98
    assert logic["grade"] == "very_strong"
    assert logic["trend"] == "unknown"
    assert logic["confidence"] == 1.0
    assert logic["factor_scores"] == {
        "earnings_delta": 35,
        "sector_theme": 20,
        "expectation_revision": 18,
        "catalyst": 15,
        "price_confirmation": 10,
    }
    assert any("EPS 超预期" in item for item in logic["drivers"])
    assert "原始叙事驱动" in logic["drivers"]


def test_logic_trend_uses_history():
    path = _history_path()
    append_logic_snapshot("NVDA", {"logic": {"score": 80, "grade": "strong"}}, history_path=path)

    result = build_logic_report(
        "NVDA",
        _fundamentals(),
        trend_report=_trend(),
        history_path=path,
    )

    assert result["logic"]["previous_score"] == 80
    assert result["logic"]["delta"] == 18
    assert result["logic"]["trend"] == "strengthening"


def test_missing_trend_lowers_price_confirmation_and_confidence():
    path = _history_path()
    result = build_logic_report(
        "NVDA",
        _fundamentals(),
        trend_report=None,
        history_path=path,
    )

    logic = result["logic"]
    assert logic["score"] == 88
    assert logic["factor_scores"]["price_confirmation"] == 0
    assert logic["confidence"] == 0.9
    assert "缺少价格验证数据" in logic["weaknesses"]


def test_weak_logic_scores_low():
    path = _history_path()
    fundamentals = _fundamentals(
        earnings={"eps_surprise_pct": -12.0},
        sector={"etf": "XLK", "trend": "bearish", "change_20d": -6.0},
        analysts={"rating": "Hold", "rating_score": 3.7, "upside_pct": -8.0},
        next_earnings={"in_window": True, "days_until": 3},
        narrative={
            "score": 3,
            "thesis": "weak",
            "earnings_catalyst": False,
            "drivers": [],
            "concerns": ["叙事弱"],
        },
    )
    trend = _trend(
        gate={"pass": False, "reason": "direction=neutral"},
        trend={"direction": "neutral"},
        continuation={"verdict": "weakening"},
    )

    result = build_logic_report(
        "BAD",
        fundamentals,
        trend_report=trend,
        history_path=path,
    )

    assert result["logic"]["score"] == 0
    assert result["logic"]["grade"] == "weak"
    assert any("EPS 大幅 miss" in item for item in result["logic"]["weaknesses"])
    assert "叙事弱" in result["logic"]["weaknesses"]


def test_error_fundamentals_returns_error():
    result = build_logic_report(
        "NVDA",
        {"status": "error", "message": "boom"},
    )

    assert result["status"] == "error"
    assert result["message"] == "boom"
