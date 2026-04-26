"""Local history helpers for logic-strength snapshots."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_HISTORY_FILE = PROJECT_ROOT / "config" / "logic_history.json"


def _history_file(history_path: str | Path | None = None) -> Path:
    return Path(history_path) if history_path is not None else DEFAULT_HISTORY_FILE


def load_history(history_path: str | Path | None = None) -> dict:
    """Load history JSON. Invalid or missing files are treated as empty."""
    path = _history_file(history_path)
    if not path.exists():
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

    return data if isinstance(data, dict) else {}


def save_history(history: dict, history_path: str | Path | None = None) -> None:
    """Persist history JSON."""
    path = _history_file(history_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False, default=str)


def get_recent_snapshots(
    ticker: str,
    limit: int = 3,
    history_path: str | Path | None = None,
) -> list[dict]:
    """Return the most recent snapshots for a ticker, oldest-to-newest."""
    history = load_history(history_path)
    snapshots = history.get(ticker.upper(), [])
    if not isinstance(snapshots, list):
        return []
    if limit <= 0:
        return snapshots
    return snapshots[-limit:]


def _snapshot_from_logic(ticker: str, logic: dict) -> dict:
    return {
        "date": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker.upper(),
        "score": logic.get("score"),
        "grade": logic.get("grade"),
        "trend": logic.get("trend"),
        "drivers": logic.get("drivers", []),
        "weaknesses": logic.get("weaknesses", []),
        "factor_scores": logic.get("factor_scores", {}),
    }


def append_logic_snapshot(
    ticker: str,
    logic_report_or_logic: dict,
    history_path: str | Path | None = None,
) -> dict:
    """Append one logic snapshot and return the saved snapshot."""
    ticker = ticker.upper()
    logic = logic_report_or_logic.get("logic", logic_report_or_logic)
    snapshot = _snapshot_from_logic(ticker, logic)

    history = load_history(history_path)
    snapshots = history.get(ticker, [])
    if not isinstance(snapshots, list):
        snapshots = []
    snapshots.append(snapshot)
    history[ticker] = snapshots
    save_history(history, history_path)
    return snapshot


def _score(snapshot: Any) -> float | None:
    if isinstance(snapshot, dict):
        value = snapshot.get("score")
    else:
        value = snapshot
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def infer_logic_trend(current_score: float, previous_snapshots: list[dict]) -> dict:
    """Infer logic trend from previous snapshots and current score.

    Rules:
    - No previous score: unknown
    - Last delta >= +8: strengthening
    - Last delta <= -8: weakening
    - Otherwise stable
    - If the previous two scores plus current are strictly monotonic, the
      three-point direction overrides the simple delta.
    """
    scores = [_score(s) for s in previous_snapshots]
    scores = [s for s in scores if s is not None]

    if not scores:
        return {
            "trend": "unknown",
            "delta": None,
            "previous_score": None,
        }

    previous_score = scores[-1]
    delta = round(float(current_score) - previous_score, 2)

    trend = "stable"
    if delta >= 8:
        trend = "strengthening"
    elif delta <= -8:
        trend = "weakening"

    recent = scores[-2:] + [float(current_score)]
    if len(recent) == 3:
        if recent[0] < recent[1] < recent[2]:
            trend = "strengthening"
        elif recent[0] > recent[1] > recent[2]:
            trend = "weakening"

    return {
        "trend": trend,
        "delta": delta,
        "previous_score": round(previous_score, 2),
    }
