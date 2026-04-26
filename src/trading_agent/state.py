"""Persistent watchlist and holdings state helpers."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_STATE_FILE = PROJECT_ROOT / "state" / "trading_state.json"
LEGACY_WATCHLIST_FILE = PROJECT_ROOT / "state" / "watchlist.json"


def _state_file(state_path: str | Path | None = None) -> Path:
    return Path(state_path) if state_path is not None else DEFAULT_STATE_FILE


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_watch_entry(item: Any) -> dict | None:
    if isinstance(item, str):
        ticker = item.strip().upper()
        if not ticker:
            return None
        return {
            "ticker": ticker,
            "added_at": None,
            "notes": "",
        }

    if not isinstance(item, dict):
        return None

    ticker = str(item.get("ticker") or "").strip().upper()
    if not ticker:
        return None

    return {
        "ticker": ticker,
        "added_at": item.get("added_at"),
        "notes": str(item.get("notes") or ""),
    }


def _normalize_holding_entry(item: Any) -> dict | None:
    if not isinstance(item, dict):
        return None

    ticker = str(item.get("ticker") or "").strip().upper()
    if not ticker:
        return None

    entry = _as_float(item.get("entry"))
    stop = _as_float(item.get("stop"))
    size = _as_float(item.get("size"))
    initial_logic_score = _as_float(item.get("initial_logic_score"))
    current_stop = _as_float(item.get("current_stop"))

    if entry is None or stop is None or size is None or initial_logic_score is None:
        return None

    normalized = {
        "ticker": ticker,
        "entry": entry,
        "stop": stop,
        "size": size,
        "opened_at": item.get("opened_at") or _utc_now(),
        "notes": str(item.get("notes") or ""),
        "initial_logic_score": initial_logic_score,
    }
    if current_stop is not None:
        normalized["current_stop"] = current_stop
    return normalized


def _dedupe_by_ticker(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for item in items:
        ticker = item["ticker"]
        if ticker in seen:
            continue
        seen.add(ticker)
        result.append(item)
    return result


def _normalize_state(data: Any) -> dict:
    watchlist_raw: Any = []
    holdings_raw: Any = []

    if isinstance(data, list):
        watchlist_raw = data
    elif isinstance(data, dict):
        watchlist_raw = data.get("watchlist", [])
        holdings_raw = data.get("holdings", [])

    watchlist = []
    for item in watchlist_raw if isinstance(watchlist_raw, list) else []:
        normalized = _normalize_watch_entry(item)
        if normalized is not None:
            watchlist.append(normalized)

    holdings = []
    for item in holdings_raw if isinstance(holdings_raw, list) else []:
        normalized = _normalize_holding_entry(item)
        if normalized is not None:
            holdings.append(normalized)

    return {
        "watchlist": _dedupe_by_ticker(watchlist),
        "holdings": _dedupe_by_ticker(holdings),
    }


def load_state(state_path: str | Path | None = None) -> dict:
    """Load state JSON. Missing or invalid files are treated as empty."""
    path = _state_file(state_path)
    read_path = path
    if state_path is None and not path.exists() and LEGACY_WATCHLIST_FILE.exists():
        read_path = LEGACY_WATCHLIST_FILE

    if not read_path.exists():
        return {"watchlist": [], "holdings": []}

    try:
        with open(read_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"watchlist": [], "holdings": []}

    return _normalize_state(data)


def save_state(state: dict, state_path: str | Path | None = None) -> dict:
    """Persist normalized state JSON and return the normalized payload."""
    path = _state_file(state_path)
    normalized = _normalize_state(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2, ensure_ascii=False, default=str)
    return normalized


def list_watch(state_path: str | Path | None = None) -> list[dict]:
    return load_state(state_path)["watchlist"]


def add_watch(
    ticker: str,
    *,
    notes: str = "",
    state_path: str | Path | None = None,
) -> dict:
    state = load_state(state_path)
    ticker = ticker.strip().upper()
    if not ticker:
        raise ValueError("ticker is required")
    for item in state["watchlist"]:
        if item["ticker"] == ticker:
            if notes and not item.get("notes"):
                item["notes"] = notes
                save_state(state, state_path)
            return item

    watch = {
        "ticker": ticker,
        "added_at": _utc_now(),
        "notes": notes,
    }
    state["watchlist"].append(watch)
    save_state(state, state_path)
    return watch


def remove_watch(ticker: str, state_path: str | Path | None = None) -> bool:
    state = load_state(state_path)
    ticker = ticker.strip().upper()
    if not ticker:
        raise ValueError("ticker is required")
    remaining = [item for item in state["watchlist"] if item["ticker"] != ticker]
    removed = len(remaining) != len(state["watchlist"])
    if removed:
        state["watchlist"] = remaining
        save_state(state, state_path)
    return removed


def list_holdings(state_path: str | Path | None = None) -> list[dict]:
    return load_state(state_path)["holdings"]


def add_holding(
    ticker: str,
    *,
    entry: float,
    stop: float,
    size: float,
    opened_at: str | None = None,
    notes: str = "",
    initial_logic_score: float,
    current_stop: float | None = None,
    state_path: str | Path | None = None,
) -> dict:
    state = load_state(state_path)
    ticker = ticker.strip().upper()
    if not ticker:
        raise ValueError("ticker is required")
    state["holdings"] = [item for item in state["holdings"] if item["ticker"] != ticker]

    holding = _normalize_holding_entry(
        {
            "ticker": ticker,
            "entry": entry,
            "stop": stop,
            "size": size,
            "opened_at": opened_at,
            "notes": notes,
            "initial_logic_score": initial_logic_score,
            "current_stop": current_stop,
        }
    )
    if holding is None:
        raise ValueError("invalid holding payload")

    state["holdings"].append(holding)
    save_state(state, state_path)
    return holding


def remove_holding(ticker: str, state_path: str | Path | None = None) -> bool:
    state = load_state(state_path)
    ticker = ticker.strip().upper()
    if not ticker:
        raise ValueError("ticker is required")
    remaining = [item for item in state["holdings"] if item["ticker"] != ticker]
    removed = len(remaining) != len(state["holdings"])
    if removed:
        state["holdings"] = remaining
        save_state(state, state_path)
    return removed


def update_holding(
    ticker: str,
    *,
    state_path: str | Path | None = None,
    **updates: Any,
) -> dict:
    state = load_state(state_path)
    ticker = ticker.strip().upper()
    if not ticker:
        raise ValueError("ticker is required")

    for index, holding in enumerate(state["holdings"]):
        if holding["ticker"] != ticker:
            continue

        merged = {**holding, **updates, "ticker": ticker}
        normalized = _normalize_holding_entry(merged)
        if normalized is None:
            raise ValueError("invalid holding payload")

        state["holdings"][index] = normalized
        save_state(state, state_path)
        return normalized

    raise KeyError(f"holding not found: {ticker}")


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def watch_main():
    parser = argparse.ArgumentParser(description="观察池管理")
    parser.add_argument("--state-path", default=None,
                        help="状态文件路径 (默认: state/trading_state.json)")
    subparsers = parser.add_subparsers(dest="action", required=True)

    add_parser = subparsers.add_parser("add", help="添加观察标的")
    add_parser.add_argument("ticker")
    add_parser.add_argument("--notes", default="")

    remove_parser = subparsers.add_parser("remove", help="移除观察标的")
    remove_parser.add_argument("ticker")

    subparsers.add_parser("list", help="列出观察池")

    args = parser.parse_args()

    try:
        if args.action == "add":
            result = add_watch(args.ticker, notes=args.notes, state_path=args.state_path)
        elif args.action == "remove":
            result = {
                "ticker": args.ticker.upper(),
                "removed": remove_watch(args.ticker, state_path=args.state_path),
            }
        else:
            result = {
                "status": "success",
                "watchlist": list_watch(state_path=args.state_path),
            }
    except Exception as e:
        _print_json({"status": "error", "message": str(e)})
        sys.exit(1)

    _print_json({"status": "success", "result": result})


def holding_main():
    parser = argparse.ArgumentParser(description="持仓状态管理")
    parser.add_argument("--state-path", default=None,
                        help="状态文件路径 (默认: state/trading_state.json)")
    subparsers = parser.add_subparsers(dest="action", required=True)

    add_parser = subparsers.add_parser("add", help="添加或覆盖持仓")
    add_parser.add_argument("ticker")
    add_parser.add_argument("--entry", type=float, required=True)
    add_parser.add_argument("--stop", type=float, required=True)
    add_parser.add_argument("--size", type=float, required=True)
    add_parser.add_argument("--initial-logic-score", type=float, required=True)
    add_parser.add_argument("--current-stop", type=float, default=None)
    add_parser.add_argument("--opened-at", default=None)
    add_parser.add_argument("--notes", default="")

    update_parser = subparsers.add_parser("update", help="更新持仓字段")
    update_parser.add_argument("ticker")
    update_parser.add_argument("--entry", type=float, default=None)
    update_parser.add_argument("--stop", type=float, default=None)
    update_parser.add_argument("--size", type=float, default=None)
    update_parser.add_argument("--initial-logic-score", type=float, default=None)
    update_parser.add_argument("--current-stop", type=float, default=None)
    update_parser.add_argument("--notes", default=None)

    remove_parser = subparsers.add_parser("remove", help="移除持仓")
    remove_parser.add_argument("ticker")

    subparsers.add_parser("list", help="列出持仓")

    args = parser.parse_args()

    try:
        if args.action == "add":
            result = add_holding(
                args.ticker,
                entry=args.entry,
                stop=args.stop,
                size=args.size,
                opened_at=args.opened_at,
                notes=args.notes,
                initial_logic_score=args.initial_logic_score,
                current_stop=args.current_stop,
                state_path=args.state_path,
            )
        elif args.action == "update":
            updates = {
                key: value
                for key, value in {
                    "entry": args.entry,
                    "stop": args.stop,
                    "size": args.size,
                    "initial_logic_score": args.initial_logic_score,
                    "current_stop": args.current_stop,
                    "notes": args.notes,
                }.items()
                if value is not None
            }
            result = update_holding(args.ticker, state_path=args.state_path, **updates)
        elif args.action == "remove":
            result = {
                "ticker": args.ticker.upper(),
                "removed": remove_holding(args.ticker, state_path=args.state_path),
            }
        else:
            result = {
                "status": "success",
                "holdings": list_holdings(state_path=args.state_path),
            }
    except Exception as e:
        _print_json({"status": "error", "message": str(e)})
        sys.exit(1)

    _print_json({"status": "success", "result": result})
