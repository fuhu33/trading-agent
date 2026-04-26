"""monitor 模块单元测试。"""

from pathlib import Path
from uuid import uuid4

from trading_agent import monitor
from trading_agent.state import add_holding, add_watch


def _analysis_report(
    *,
    ticker: str,
    price: float = 100.0,
    gate_pass: bool = True,
    logic_trend: str = "stable",
    continuation: str = "strong",
    decision_action: str = "enter",
    exit_signals: list[str] | None = None,
) -> dict:
    return {
        "status": "success",
        "ticker": ticker,
        "trend_report": {
            "price": {"close": price},
            "gate": {
                "pass": gate_pass,
                "reason": "ok" if gate_pass else "direction=neutral",
            },
            "continuation": {"verdict": continuation},
        },
        "logic_report": {
            "logic": {
                "trend": logic_trend,
            }
        },
        "decision_report": {
            "action": decision_action,
            "exit_signals": exit_signals or [],
        },
    }


def _state_path():
    root = Path(".test_artifacts")
    root.mkdir(exist_ok=True)
    return root / f"trading_state_{uuid4().hex}.json"


def test_build_monitor_report_for_watchlist(monkeypatch):
    state_path = _state_path()
    add_watch("nvda", state_path=state_path)

    monkeypatch.setattr(
        monitor.analyzer,
        "build_analysis_report",
        lambda ticker, **kwargs: _analysis_report(ticker=ticker, decision_action="enter"),
    )

    report = monitor.build_monitor_report(state_path=state_path)

    assert report["status"] == "success"
    assert len(report["items"]) == 1
    item = report["items"][0]
    assert item["ticker"] == "NVDA"
    assert item["type"] == "watch"
    assert item["monitor_action"] == "enter"
    assert item["alerts"] == []


def test_build_monitor_report_for_holding_alerts(monkeypatch):
    state_path = _state_path()
    add_holding(
        "aapl",
        entry=100,
        stop=95,
        current_stop=97,
        size=5,
        opened_at="2026-04-25T00:00:00+00:00",
        notes="swing",
        initial_logic_score=82,
        state_path=state_path,
    )

    monkeypatch.setattr(
        monitor.analyzer,
        "build_analysis_report",
        lambda ticker, **kwargs: _analysis_report(
            ticker=ticker,
            price=96.0,
            gate_pass=False,
            logic_trend="weakening",
            continuation="weakening",
            decision_action="watch",
        ),
    )

    report = monitor.build_monitor_report(state_path=state_path)
    item = report["items"][0]

    assert item["ticker"] == "AAPL"
    assert item["type"] == "holding"
    assert item["monitor_action"] == "exit"
    assert item["alerts"] == [
        "price <= stop (96.00 <= 97.00)",
        "Gate FAIL",
        "logic.trend weakening",
        "continuation weakening",
    ]

    markdown = monitor.format_monitor_markdown(report)
    assert "AAPL [holding] -> exit" in markdown
    assert "Gate FAIL" in markdown
