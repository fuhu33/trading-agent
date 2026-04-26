"""Single-ticker analysis orchestration.

This module is the stable code entry point for the Agent workflow:
fundamentals -> logic -> trend -> decision -> risk -> report.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .fundamentals import build_fundamentals_report, flush_cache
from .logic import build_logic_report
from .trend import build_trend_report
from .decision import build_decision_report
from .risk import calculate_risk
from .reporter import render_analysis_markdown


def _write_output(path: str, content: str) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")


ATR_MULTIPLIER_BY_STAGE = {
    "early": 2.0,
    "mid": 1.5,
    "late": 1.2,
}


def _component_warning(component: str, report: dict) -> dict | None:
    """Return a warning for non-critical component failures."""
    if not isinstance(report, dict) or report.get("status") != "error":
        return None
    return {
        "component": component,
        "message": report.get("message", "unknown error"),
    }


def _build_risk_report(
    trend_report: dict,
    decision_report: dict,
    account: float,
    base_risk_pct: float,
) -> dict | None:
    """Build a concrete RiskReport when the decision allows an entry."""
    multiplier = float(decision_report.get("position_multiplier") or 0)
    if not decision_report.get("entry_allowed") or multiplier <= 0:
        return None

    price = trend_report.get("price", {})
    levels = trend_report.get("levels", {})
    fish = trend_report.get("fish_body", {})

    entry = float(price.get("close") or 0)
    atr = float(levels.get("atr") or 0)
    if entry <= 0 or atr <= 0:
        return None

    stage = fish.get("stage", "mid")
    atr_multiple = ATR_MULTIPLIER_BY_STAGE.get(stage, 1.5)
    stop = entry - atr * atr_multiple
    if stop <= 0:
        return None

    effective_risk_pct = min(base_risk_pct * multiplier, 0.1)
    risk_report = calculate_risk(
        entry=entry,
        stop=stop,
        account=account,
        risk_pct=effective_risk_pct,
        atr=atr,
    )
    risk_report["atr_multiple_used"] = atr_multiple
    return risk_report


def build_analysis_report(
    ticker: str,
    account: float = 100000,
    risk_pct: float = 0.02,
    days: int = 90,
    save_history: bool = False,
    force_fundamentals: bool = False,
) -> dict:
    """Run the full single-ticker analysis pipeline."""
    ticker = ticker.upper()

    fundamentals_report = build_fundamentals_report(
        ticker,
        force_refresh=force_fundamentals,
    )
    trend_report = build_trend_report(ticker, days=days)
    logic_report = build_logic_report(
        ticker,
        fundamentals_report,
        trend_report=trend_report,
        save_history=save_history,
    )
    decision_report = build_decision_report(
        ticker,
        trend_report,
        logic_report,
        fundamentals_report=fundamentals_report,
        account=account,
        risk_pct=risk_pct,
    )
    risk_report = _build_risk_report(
        trend_report=trend_report,
        decision_report=decision_report,
        account=account,
        base_risk_pct=risk_pct,
    )

    warnings = [
        warning
        for warning in [
            _component_warning("fundamentals", fundamentals_report),
            _component_warning("logic", logic_report),
        ]
        if warning is not None
    ]
    status = "degraded" if warnings else "success"

    return {
        "status": status,
        "ticker": ticker,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "account": round(account, 2),
        "base_risk_pct": risk_pct,
        "warnings": warnings,
        "fundamentals_report": fundamentals_report,
        "trend_report": trend_report,
        "logic_report": logic_report,
        "decision_report": decision_report,
        "risk_report": risk_report,
    }


def main():
    parser = argparse.ArgumentParser(description="单标的完整 Agent 分析")
    parser.add_argument("ticker", help="品种代码 (如 NVDA, AAPL, XAU)")
    parser.add_argument("--account", type=float, default=100000,
                        help="账户总资金 (默认: 100000)")
    parser.add_argument("--risk-pct", type=float, default=0.02,
                        help="基础单笔风险比例 (默认: 0.02 = 2%%)")
    parser.add_argument("--days", type=int, default=90,
                        help="技术面回看天数 (默认: 90)")
    parser.add_argument("--json", action="store_true",
                        help="输出 JSON 格式 (默认: Markdown 报告)")
    parser.add_argument("--output",
                        help="将输出保存到指定文件路径 (格式跟随 --json)")
    parser.add_argument("--no-save-history", action="store_true",
                        help="不写入逻辑强度历史")
    parser.add_argument("--force-fund", action="store_true",
                        help="跳过基本面缓存")
    args = parser.parse_args()

    try:
        report = build_analysis_report(
            args.ticker,
            account=args.account,
            risk_pct=args.risk_pct,
            days=args.days,
            save_history=not args.no_save_history,
            force_fundamentals=args.force_fund,
        )
        flush_cache()
    except Exception as e:
        error = {
            "status": "error",
            "ticker": args.ticker.upper(),
            "message": str(e),
        }
        print(json.dumps(error, ensure_ascii=False))
        sys.exit(1)

    if args.json:
        output = json.dumps(report, indent=2, ensure_ascii=False, default=str)
    else:
        output = render_analysis_markdown(report)

    if args.output:
        _write_output(args.output, output)

    print(output)


if __name__ == "__main__":
    main()
