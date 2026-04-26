"""Batch research orchestration built on top of scanner and analyzer."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from importlib import import_module

scanner = None
analyzer = None

ACTION_PRIORITY = {
    "enter": 3,
    "small_enter": 2,
    "watch": 1,
    "reject": 0,
}

STAGE_PRIORITY = {
    "early": 2,
    "mid": 1,
    "late": 0,
}

CONTINUATION_PRIORITY = {
    "strong": 2,
    "moderate": 1,
    "weakening": 0,
}


def _normalize_tickers_arg(tickers: str | list[str] | tuple[str, ...] | None) -> str | None:
    if tickers is None:
        return None
    if isinstance(tickers, str):
        return tickers
    return ",".join(str(ticker).strip() for ticker in tickers if str(ticker).strip())


def _get_scanner_module():
    global scanner
    if scanner is None:
        scanner = import_module(".scanner", __package__)
    return scanner


def _get_analyzer_module():
    global analyzer
    if analyzer is None:
        analyzer = import_module(".analyzer", __package__)
    return analyzer


def _ranking_key(analysis_report: dict) -> tuple:
    decision_report = analysis_report.get("decision_report") or {}
    logic = (analysis_report.get("logic_report") or {}).get("logic") or {}
    trend_report = analysis_report.get("trend_report") or {}
    fish_body = trend_report.get("fish_body") or {}
    continuation = trend_report.get("continuation") or {}

    entry_allowed = 1 if decision_report.get("entry_allowed") else 0
    action_priority = ACTION_PRIORITY.get(decision_report.get("action"), -1)
    logic_score = float(logic.get("score") or 0)
    logic_trend = 1 if logic.get("trend") == "strengthening" else 0
    stage_priority = STAGE_PRIORITY.get(fish_body.get("stage"), -1)
    continuation_priority = CONTINUATION_PRIORITY.get(continuation.get("verdict"), -1)
    ideal_entry = 1 if fish_body.get("ideal_entry") else 0
    position_multiplier = float(decision_report.get("position_multiplier") or 0)
    ticker = analysis_report.get("ticker", "")

    return (
        -entry_allowed,
        -action_priority,
        -logic_score,
        -logic_trend,
        -stage_priority,
        -continuation_priority,
        -ideal_entry,
        -position_multiplier,
        ticker,
    )


def _build_candidate_summary(scan_result: dict, analysis_report: dict) -> dict:
    decision_report = analysis_report.get("decision_report") or {}
    logic = (analysis_report.get("logic_report") or {}).get("logic") or {}
    trend_report = analysis_report.get("trend_report") or {}
    fish_body = trend_report.get("fish_body") or {}
    continuation = trend_report.get("continuation") or {}

    return {
        "ticker": analysis_report.get("ticker", scan_result.get("ticker")),
        "action": decision_report.get("action"),
        "entry_allowed": bool(decision_report.get("entry_allowed")),
        "logic_score": logic.get("score"),
        "logic_trend": logic.get("trend"),
        "stage": fish_body.get("stage"),
        "continuation": continuation.get("verdict"),
        "ideal_entry": bool(fish_body.get("ideal_entry")),
        "position_multiplier": decision_report.get("position_multiplier"),
        "analysis_status": analysis_report.get("status"),
        "warnings": analysis_report.get("warnings", []),
        "gate_reason": scan_result.get("gate_reason"),
        "scan_result": scan_result,
    }


def build_research_report(
    tickers: str | list[str] | tuple[str, ...] | None = None,
    group: str = "mega_cap",
    limit: int = 3,
    delay: float = 1.5,
    account: float = 100000,
    risk_pct: float = 0.02,
    days: int = 90,
    save_history: bool = False,
    with_fund: bool = True,
) -> dict:
    """Scan a universe, deeply analyze Gate-pass names, then rank the results."""
    scanner_module = _get_scanner_module()
    analyzer_module = _get_analyzer_module()
    tickers_csv = _normalize_tickers_arg(tickers)
    resolved_tickers = scanner_module.resolve_tickers(tickers_csv, group)
    scan_results = scanner_module.scan_batch(
        resolved_tickers,
        delay=delay,
        with_fund=with_fund,
    )

    generated_at = datetime.now(timezone.utc).isoformat()
    errors: list[dict] = []
    gate_pass_candidates: list[dict] = []

    for result in scan_results:
        if result.get("status") == "error":
            errors.append(
                {
                    "stage": "scan",
                    "ticker": result.get("ticker"),
                    "message": result.get("message", "unknown scan error"),
                }
            )
            continue
        if result.get("gate_pass"):
            gate_pass_candidates.append(result)

    successful_analyses: list[dict] = []

    for candidate in gate_pass_candidates:
        ticker = candidate.get("ticker")
        try:
            analysis_report = analyzer_module.build_analysis_report(
                ticker,
                account=account,
                risk_pct=risk_pct,
                days=days,
                save_history=save_history,
            )
        except Exception as exc:
            errors.append(
                {
                    "stage": "analysis",
                    "ticker": ticker,
                    "message": str(exc),
                    "scan_result": candidate,
                }
            )
            continue

        if analysis_report.get("status") not in {"success", "degraded"}:
            errors.append(
                {
                    "stage": "analysis",
                    "ticker": ticker,
                    "message": analysis_report.get("message", "analysis failed"),
                    "scan_result": candidate,
                }
            )
            continue

        successful_analyses.append(
            {
                "ticker": ticker,
                "scan_result": candidate,
                "analysis_report": analysis_report,
            }
        )

    ranked_entries = sorted(
        successful_analyses,
        key=lambda item: _ranking_key(item["analysis_report"]),
    )

    if limit < 0:
        limit = 0
    ranked_entries = ranked_entries[:limit]

    candidates: list[dict] = []
    analyses: list[dict] = []

    for rank, entry in enumerate(ranked_entries, start=1):
        candidate_summary = _build_candidate_summary(
            entry["scan_result"],
            entry["analysis_report"],
        )
        candidate_summary["rank"] = rank
        candidates.append(candidate_summary)
        analyses.append(
            {
                "rank": rank,
                "ticker": entry["ticker"],
                "report": entry["analysis_report"],
            }
        )

    return {
        "status": "success",
        "generated_at": generated_at,
        "summary": {
            "group": group,
            "requested_tickers": resolved_tickers,
            "scanned": len(scan_results),
            "gate_pass": len(gate_pass_candidates),
            "analyzed": len(successful_analyses),
            "returned": len(candidates),
            "errors": len(errors),
            "limit": limit,
        },
        "candidates": candidates,
        "analyses": analyses,
        "errors": errors,
    }


def format_research_markdown(report: dict) -> str:
    """Render a compact Markdown view of a research report."""
    summary = report.get("summary") or {}
    candidates = report.get("candidates") or []
    errors = report.get("errors") or []

    lines = [
        "# Research Report",
        "",
        f"- Generated: {report.get('generated_at', '-')}",
        f"- Group: {summary.get('group', '-')}",
        (
            f"- Universe: {summary.get('scanned', 0)} scanned / "
            f"{summary.get('gate_pass', 0)} gate-pass / "
            f"{summary.get('analyzed', 0)} analyzed / "
            f"{summary.get('returned', 0)} ranked"
        ),
    ]

    if candidates:
        lines.extend(
            [
                "",
                "## Ranked Candidates",
                "",
                "| Rank | Ticker | Action | Logic | Trend | Stage | Continuation | Ideal | Position |",
                "|------|--------|--------|-------|-------|-------|--------------|-------|----------|",
            ]
        )
        for candidate in candidates:
            lines.append(
                "| {rank} | {ticker} | {action} | {logic_score} | {logic_trend} | {stage} | "
                "{continuation} | {ideal_entry} | {position_multiplier} |".format(
                    rank=candidate.get("rank", "-"),
                    ticker=candidate.get("ticker", "-"),
                    action=candidate.get("action", "-"),
                    logic_score=candidate.get("logic_score", "-"),
                    logic_trend=candidate.get("logic_trend", "-"),
                    stage=candidate.get("stage", "-"),
                    continuation=candidate.get("continuation", "-"),
                    ideal_entry="yes" if candidate.get("ideal_entry") else "no",
                    position_multiplier=candidate.get("position_multiplier", "-"),
                )
            )
    else:
        lines.extend(["", "## Ranked Candidates", "", "_No ranked candidates._"])

    if errors:
        lines.extend(["", "## Errors", ""])
        for error in errors:
            lines.append(
                f"- {error.get('stage', 'unknown')} / {error.get('ticker', '-')}: {error.get('message', '-')}"
            )

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="扫描后深度研究与候选排名")
    parser.add_argument("tickers", nargs="?", default=None,
                        help="逗号分隔的品种代码 (如 AAPL,MSFT,NVDA)")
    parser.add_argument("--group", default="mega_cap",
                        choices=["all", "stock", "etf", "commodity", "mega_cap"],
                        help="扫描分组 (默认: mega_cap)")
    parser.add_argument("--limit", type=int, default=3,
                        help="返回排名候选数量 (默认: 3)")
    parser.add_argument("--delay", type=float, default=1.5,
                        help="扫描请求间隔秒数 (默认: 1.5)")
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
    parser.add_argument("--no-fund", action="store_true",
                        help="扫描阶段不拉取基本面摘要")
    args = parser.parse_args()

    try:
        report = build_research_report(
            tickers=args.tickers,
            group=args.group,
            limit=args.limit,
            delay=args.delay,
            account=args.account,
            risk_pct=args.risk_pct,
            days=args.days,
            save_history=not args.no_save_history,
            with_fund=not args.no_fund,
        )
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
        sys.exit(1)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        print(format_research_markdown(report))


if __name__ == "__main__":
    main()
