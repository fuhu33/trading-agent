"""analyzer 编排层测试。"""

from trading_agent import analyzer
from trading_agent.reporter import render_analysis_markdown


def _fundamentals():
    return {
        "status": "success",
        "ticker": "NVDA",
        "next_earnings": {"in_window": False},
        "analysts": {"upside_pct": 12.0},
        "narrative": {"thesis": "strong", "earnings_catalyst": False},
    }


def _trend(gate_pass=True):
    return {
        "status": "success",
        "ticker": "NVDA",
        "price": {"close": 100.0, "change_pct": 1.0},
        "trend": {"direction": "bullish", "strength": "strong", "adx": 30},
        "fish_body": {"stage": "mid", "ideal_entry": True},
        "continuation": {"verdict": "strong", "volume_ratio": 1.2, "risk_flags": []},
        "levels": {"ema20": 96.0, "ema50": 90.0, "recent_high": 105.0, "atr": 4.0},
        "gate": {
            "pass": gate_pass,
            "reason": "ADX=30 >= 20" if gate_pass else "direction=neutral",
        },
        "raw": {"rsi": 55.0},
    }


def _logic():
    return {
        "status": "success",
        "ticker": "NVDA",
        "logic": {
            "score": 70,
            "grade": "strong",
            "trend": "stable",
            "delta": None,
            "previous_score": None,
            "confidence": 1.0,
            "drivers": ["logic driver"],
            "weaknesses": [],
            "factor_scores": {},
        },
    }


def _logic_error():
    return {
        "status": "error",
        "ticker": "NVDA",
        "message": "fundamentals unavailable",
    }


def test_build_analysis_report_orchestrates_pipeline(monkeypatch):
    monkeypatch.setattr(analyzer, "build_fundamentals_report", lambda *args, **kwargs: _fundamentals())
    monkeypatch.setattr(analyzer, "build_trend_report", lambda *args, **kwargs: _trend())
    monkeypatch.setattr(analyzer, "build_logic_report", lambda *args, **kwargs: _logic())

    report = analyzer.build_analysis_report(
        "nvda",
        account=100000,
        risk_pct=0.02,
        save_history=False,
    )

    assert report["status"] == "success"
    assert report["ticker"] == "NVDA"
    assert report["decision_report"]["action"] == "enter"
    assert report["decision_report"]["position_multiplier"] == 1.2
    assert report["decision_report"]["final_risk_pct"] == 0.024
    assert report["risk_report"]["entry"] == 100.0
    assert report["risk_report"]["stop"] == 94.0
    assert report["risk_report"]["risk_amount"] == 2400.0


def test_build_analysis_report_skips_risk_when_entry_not_allowed(monkeypatch):
    monkeypatch.setattr(analyzer, "build_fundamentals_report", lambda *args, **kwargs: _fundamentals())
    monkeypatch.setattr(analyzer, "build_trend_report", lambda *args, **kwargs: _trend(gate_pass=False))
    monkeypatch.setattr(analyzer, "build_logic_report", lambda *args, **kwargs: _logic())

    report = analyzer.build_analysis_report("NVDA", save_history=False)

    assert report["decision_report"]["entry_allowed"] is False
    assert report["risk_report"] is None


def test_build_analysis_report_marks_noncritical_failures_as_degraded(monkeypatch):
    monkeypatch.setattr(
        analyzer,
        "build_fundamentals_report",
        lambda *args, **kwargs: {
            "status": "error",
            "ticker": "NVDA",
            "message": "yfinance unavailable",
        },
    )
    monkeypatch.setattr(analyzer, "build_trend_report", lambda *args, **kwargs: _trend())
    monkeypatch.setattr(analyzer, "build_logic_report", lambda *args, **kwargs: _logic_error())

    report = analyzer.build_analysis_report("NVDA", save_history=False)

    assert report["status"] == "degraded"
    assert report["warnings"] == [
        {"component": "fundamentals", "message": "yfinance unavailable"},
        {"component": "logic", "message": "fundamentals unavailable"},
    ]
    assert report["decision_report"]["entry_allowed"] is False


def test_render_analysis_markdown_shows_degraded_warnings(monkeypatch):
    monkeypatch.setattr(
        analyzer,
        "build_fundamentals_report",
        lambda *args, **kwargs: {
            "status": "error",
            "ticker": "NVDA",
            "message": "yfinance unavailable",
        },
    )
    monkeypatch.setattr(analyzer, "build_trend_report", lambda *args, **kwargs: _trend())
    monkeypatch.setattr(analyzer, "build_logic_report", lambda *args, **kwargs: _logic_error())

    output = render_analysis_markdown(analyzer.build_analysis_report("NVDA"))

    assert "数据降级" in output
    assert "yfinance unavailable" in output
