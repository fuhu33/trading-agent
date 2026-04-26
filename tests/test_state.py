"""state 模块单元测试。"""

from pathlib import Path
from uuid import uuid4

from trading_agent.state import (
    add_holding,
    add_watch,
    list_holdings,
    list_watch,
    load_state,
    remove_holding,
    remove_watch,
    update_holding,
)


def _state_path():
    root = Path(".test_artifacts")
    root.mkdir(exist_ok=True)
    return root / f"trading_state_{uuid4().hex}.json"


def test_add_watch_deduplicates_by_ticker():
    state_path = _state_path()

    first = add_watch("nvda", notes="first", state_path=state_path)
    second = add_watch("NVDA", notes="second", state_path=state_path)

    assert first["ticker"] == "NVDA"
    assert second["ticker"] == "NVDA"
    assert len(list_watch(state_path)) == 1
    assert list_watch(state_path)[0]["notes"] == "first"

    assert remove_watch("nvda", state_path) is True
    assert list_watch(state_path) == []


def test_add_update_and_remove_holding():
    state_path = _state_path()

    created = add_holding(
        "msft",
        entry=100,
        stop=92,
        size=10,
        opened_at="2026-04-25T00:00:00+00:00",
        notes="starter",
        initial_logic_score=78,
        state_path=state_path,
    )

    assert created["ticker"] == "MSFT"
    assert created["stop"] == 92.0
    assert created["initial_logic_score"] == 78.0

    updated = update_holding(
        "MSFT",
        current_stop=96,
        size=12,
        notes="raised stop",
        state_path=state_path,
    )

    assert updated["current_stop"] == 96.0
    assert updated["size"] == 12.0
    assert updated["notes"] == "raised stop"
    assert list_holdings(state_path)[0]["ticker"] == "MSFT"

    saved = load_state(state_path)
    assert saved["holdings"][0]["current_stop"] == 96.0

    assert remove_holding("msft", state_path) is True
    assert list_holdings(state_path) == []
