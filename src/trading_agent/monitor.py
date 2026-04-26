"""Watchlist and holdings monitoring helpers."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from . import analyzer
from .state import load_state


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _price_from_analysis(analysis: dict) -> float | None:
    try:
        return float(analysis.get("trend_report", {}).get("price", {}).get("close"))
    except (TypeError, ValueError):
        return None


def _build_watch_item(ticker: str, analysis: dict) -> dict:
    decision = analysis.get("decision_report", {}) if isinstance(analysis, dict) else {}
    alerts = list(decision.get("exit_signals") or [])
    return {
        "ticker": ticker,
        "type": "watch",
        "analysis": analysis,
        "monitor_action": decision.get("action", "watch"),
        "alerts": alerts,
    }


def _build_holding_item(ticker: str, holding: dict, analysis: dict) -> dict:
    trend_report = analysis.get("trend_report", {}) if isinstance(analysis, dict) else {}
    logic = analysis.get("logic_report", {}).get("logic", {}) if isinstance(analysis, dict) else {}
    continuation = trend_report.get("continuation", {}) if isinstance(trend_report, dict) else {}
    gate = trend_report.get("gate", {}) if isinstance(trend_report, dict) else {}

    alerts: list[str] = []
    price = _price_from_analysis(analysis)
    active_stop = holding.get("current_stop", holding.get("stop"))
    stop_hit = price is not None and active_stop is not None and price <= float(active_stop)
    gate_fail = not bool(gate.get("pass", False))
    logic_weakening = str(logic.get("trend") or "").lower() == "weakening"
    continuation_weakening = str(continuation.get("verdict") or "").lower() == "weakening"

    if stop_hit:
        alerts.append(f"price <= stop ({price:.2f} <= {float(active_stop):.2f})")
    if gate_fail:
        alerts.append("Gate FAIL")
    if logic_weakening:
        alerts.append("logic.trend weakening")
    if continuation_weakening:
        alerts.append("continuation weakening")

    if stop_hit or gate_fail:
        action = "exit"
    elif logic_weakening and continuation_weakening:
        action = "reduce"
    elif logic_weakening or continuation_weakening:
        action = "review"
    else:
        action = "hold"

    return {
        "ticker": ticker,
        "type": "holding",
        "analysis": analysis,
        "monitor_action": action,
        "alerts": alerts,
    }


def build_monitor_report(
    *,
    state_path: str | None = None,
    account: float = 100000,
    risk_pct: float = 0.02,
    days: int = 90,
    save_history: bool = False,
    force_fundamentals: bool = False,
) -> dict:
    """Analyze watchlist and holdings and return a structured monitor report."""
    state = load_state(state_path)
    items: list[dict] = []
    failures = 0

    for watch in state.get("watchlist", []):
        ticker = watch["ticker"]
        try:
            analysis = analyzer.build_analysis_report(
                ticker,
                account=account,
                risk_pct=risk_pct,
                days=days,
                save_history=save_history,
                force_fundamentals=force_fundamentals,
            )
            items.append(_build_watch_item(ticker, analysis))
        except Exception as exc:
            failures += 1
            items.append(
                {
                    "ticker": ticker,
                    "type": "watch",
                    "analysis": {"status": "error", "message": str(exc)},
                    "monitor_action": "error",
                    "alerts": [str(exc)],
                }
            )

    for holding in state.get("holdings", []):
        ticker = holding["ticker"]
        try:
            analysis = analyzer.build_analysis_report(
                ticker,
                account=account,
                risk_pct=risk_pct,
                days=days,
                save_history=save_history,
                force_fundamentals=force_fundamentals,
            )
            items.append(_build_holding_item(ticker, holding, analysis))
        except Exception as exc:
            failures += 1
            items.append(
                {
                    "ticker": ticker,
                    "type": "holding",
                    "analysis": {"status": "error", "message": str(exc)},
                    "monitor_action": "error",
                    "alerts": [str(exc)],
                }
            )

    status = "success"
    if failures and failures == len(items):
        status = "error"
    elif failures:
        status = "partial"

    return {
        "status": status,
        "generated_at": _utc_now(),
        "items": items,
    }


def format_monitor_markdown(report: dict) -> str:
    """Render a compact Markdown summary for monitor output."""
    lines = [
        "## Monitor Report",
        "",
        f"- Status: {report.get('status', '-')}",
        f"- Generated: {report.get('generated_at', '-')}",
    ]

    items = report.get("items") or []
    if not items:
        lines.extend(["", "- No watchlist or holdings found."])
        return "\n".join(lines)

    lines.append("")
    for item in items:
        ticker = item.get("ticker", "-")
        item_type = item.get("type", "-")
        action = item.get("monitor_action", "-")
        alerts = item.get("alerts") or []
        alert_text = "; ".join(str(alert) for alert in alerts) if alerts else "none"
        lines.append(f"- {ticker} [{item_type}] -> {action} | alerts: {alert_text}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="观察池与持仓监控")
    parser.add_argument("--state-path", default=None,
                        help="状态文件路径 (默认: state/trading_state.json)")
    parser.add_argument("--account", type=float, default=100000,
                        help="账户总资金 (默认: 100000)")
    parser.add_argument("--risk-pct", type=float, default=0.02,
                        help="基础单笔风险比例 (默认: 0.02 = 2%%)")
    parser.add_argument("--days", type=int, default=90,
                        help="技术面回看天数 (默认: 90)")
    parser.add_argument("--json", action="store_true",
                        help="输出 JSON 格式 (默认: Markdown)")
    parser.add_argument("--no-save-history", action="store_true",
                        help="不写入逻辑强度历史")
    parser.add_argument("--force-fund", action="store_true",
                        help="跳过基本面缓存")
    args = parser.parse_args()

    try:
        report = build_monitor_report(
            state_path=args.state_path,
            account=args.account,
            risk_pct=args.risk_pct,
            days=args.days,
            save_history=not args.no_save_history,
            force_fundamentals=args.force_fund,
        )
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
        sys.exit(1)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        print(format_monitor_markdown(report))


if __name__ == "__main__":
    main()
