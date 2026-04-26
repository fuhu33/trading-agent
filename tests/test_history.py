"""history 模块单元测试。"""

from pathlib import Path
from uuid import uuid4

from trading_agent.history import (
    append_logic_snapshot,
    get_recent_snapshots,
    infer_logic_trend,
)


def _history_path():
    root = Path(".test_artifacts")
    root.mkdir(exist_ok=True)
    return root / f"logic_history_{uuid4().hex}.json"


def test_missing_history_returns_empty():
    path = _history_path()

    assert get_recent_snapshots("NVDA", history_path=path) == []


def test_append_and_read_snapshot():
    path = _history_path()
    report = {
        "logic": {
            "score": 72,
            "grade": "strong",
            "trend": "stable",
            "drivers": ["EPS beat"],
            "weaknesses": [],
            "factor_scores": {"earnings_delta": 28},
        }
    }

    saved = append_logic_snapshot("nvda", report, history_path=path)
    recent = get_recent_snapshots("NVDA", history_path=path)

    assert saved["ticker"] == "NVDA"
    assert recent[-1]["score"] == 72
    assert recent[-1]["drivers"] == ["EPS beat"]
    path.unlink(missing_ok=True)


def test_infer_unknown_when_no_history():
    result = infer_logic_trend(70, [])

    assert result == {
        "trend": "unknown",
        "delta": None,
        "previous_score": None,
    }


def test_infer_strengthening_by_delta():
    result = infer_logic_trend(73, [{"score": 64}])

    assert result["trend"] == "strengthening"
    assert result["delta"] == 9
    assert result["previous_score"] == 64


def test_infer_weakening_by_delta():
    result = infer_logic_trend(55, [{"score": 66}])

    assert result["trend"] == "weakening"
    assert result["delta"] == -11


def test_three_point_direction_overrides_small_delta():
    strengthening = infer_logic_trend(66, [{"score": 62}, {"score": 64}])
    weakening = infer_logic_trend(62, [{"score": 66}, {"score": 64}])

    assert strengthening["trend"] == "strengthening"
    assert strengthening["delta"] == 2
    assert weakening["trend"] == "weakening"
    assert weakening["delta"] == -2
