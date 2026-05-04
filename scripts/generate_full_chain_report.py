"""Generate a full-chain trading-agent HTML report."""

from __future__ import annotations

import argparse
import html
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def disable_yfinance_sqlite_cache() -> None:
    """Avoid yfinance sqlite cache writes in restricted local workspaces."""
    try:
        import yfinance.cache as yf_cache

        yf_cache._CookieCacheManager._Cookie_cache = yf_cache._CookieCacheDummy()
        yf_cache._TzCacheManager._tz_cache = yf_cache._TzCacheDummy()
    except Exception:
        return


disable_yfinance_sqlite_cache()

from scripts.generate_us_stock_sentiment_report import (  # noqa: E402
    collect_candidate_symbols,
    fmt_num,
    fmt_pct,
    json_default,
    reliability_score,
)
from trading_agent.analyzer import build_analysis_report  # noqa: E402
from trading_agent.fundamentals import flush_cache  # noqa: E402
from trading_agent.research import _ranking_key  # noqa: E402
from trading_agent.scanner import scan_batch  # noqa: E402
from trading_agent.sentiment import build_market_sentiment_report  # noqa: E402
from trading_agent.symbols import get_symbols, invalidate_index  # noqa: E402


STATE_LABELS = {
    "RISK_OFF": "退潮",
    "COLD": "冰点",
    "RECOVERY_CANDIDATE": "回暖候选",
    "RISK_ON": "强势",
    "DIVERGENCE": "分歧",
}

ACTION_LABELS = {
    "enter": "入场",
    "small_enter": "小仓试单",
    "watch": "观察",
    "hold": "持有",
    "reduce": "减仓",
    "exit": "退出",
    "reject": "拒绝",
}

STAGE_LABELS = {
    "early": "鱼头",
    "mid": "鱼身",
    "late": "鱼尾",
    "n/a": "-",
}

GROUP_LABELS = {
    "stock": "股票",
    "etf": "ETF",
    "commodity": "商品",
}


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def write_files(output_dir: Path, stem: str, payload: dict[str, Any],
                html_text: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / f"{stem}.html"
    json_path = output_dir / f"{stem}.json"
    try:
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=json_default),
            encoding="utf-8",
        )
        html_path.write_text(html_text, encoding="utf-8")
        return html_path, json_path
    except PermissionError:
        fallback = ROOT / "generated_reports"
        if output_dir.resolve() == fallback.resolve():
            raise
        return write_files(fallback, stem, payload, html_text)


def group_counts(symbols: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for symbol in symbols:
        group = str(symbol.get("group") or "unknown")
        counts[group] = counts.get(group, 0) + 1
    return counts


def run_sentiment(args: argparse.Namespace) -> dict[str, Any]:
    tickers, quotes = collect_candidate_symbols(args.sentiment_candidates)
    report = build_market_sentiment_report(
        tickers,
        top_n=args.sentiment_top,
        compare_top_n=tuple(args.sentiment_compare),
        period=args.sentiment_period,
        chunk_size=args.sentiment_chunk_size,
        retries=args.sentiment_retries,
        retry_sleep=args.sentiment_retry_sleep,
        use_cache=args.use_sentiment_cache,
        refresh_cache=not args.use_sentiment_cache,
        validate=True,
        benchmark_tickers=("SPY", "QQQ"),
        forward_days=(1, 3, 5),
    )
    return {
        "candidate_tickers": tickers,
        "candidate_quotes": quotes,
        "report": report,
    }


def run_trading_chain(args: argparse.Namespace) -> dict[str, Any]:
    if args.force_sync:
        invalidate_index()
    symbols_report = get_symbols(force=args.force_sync)
    symbols = list(symbols_report.get("symbols") or [])
    if args.group != "all":
        symbols = [item for item in symbols if item.get("group") == args.group]
    tickers = [str(item["baseCoin"]).upper() for item in symbols]

    scan_started = time.time()
    scan_results = scan_batch(
        tickers,
        delay=args.scan_delay,
        with_fund=True,
    )
    scan_elapsed = round(time.time() - scan_started, 2)
    flush_cache()

    gate_pass = [
        item for item in scan_results
        if item.get("status") == "success" and item.get("gate_pass")
    ]
    analysis_entries: list[dict[str, Any]] = []
    analysis_errors: list[dict[str, Any]] = []
    analysis_started = time.time()
    for item in gate_pass:
        ticker = str(item.get("ticker") or "").upper()
        try:
            analysis = build_analysis_report(
                ticker,
                account=args.account,
                risk_pct=args.risk_pct,
                days=args.days,
                save_history=False,
            )
            analysis_entries.append({
                "ticker": ticker,
                "scan_result": item,
                "analysis_report": analysis,
            })
        except Exception as exc:
            analysis_errors.append({
                "ticker": ticker,
                "stage": "analysis",
                "message": str(exc),
                "scan_result": item,
            })
    analysis_elapsed = round(time.time() - analysis_started, 2)
    flush_cache()

    ranked = sorted(
        analysis_entries,
        key=lambda entry: _ranking_key(entry["analysis_report"]),
    )
    return {
        "symbols_report": symbols_report,
        "symbols": symbols,
        "tickers": tickers,
        "scan_results": scan_results,
        "gate_pass": gate_pass,
        "analysis_entries": analysis_entries,
        "analysis_errors": analysis_errors,
        "ranked": ranked,
        "timing": {
            "scan_seconds": scan_elapsed,
            "analysis_seconds": analysis_elapsed,
        },
    }


def scan_summary(scan_results: list[dict[str, Any]]) -> dict[str, Any]:
    success = [item for item in scan_results if item.get("status") == "success"]
    errors = [item for item in scan_results if item.get("status") == "error"]
    gate_pass = [item for item in success if item.get("gate_pass")]
    by_group: dict[str, dict[str, int]] = {}
    for item in success:
        group = str(item.get("group") or "unknown")
        bucket = by_group.setdefault(group, {"total": 0, "gate_pass": 0})
        bucket["total"] += 1
        if item.get("gate_pass"):
            bucket["gate_pass"] += 1
    return {
        "total": len(scan_results),
        "success": len(success),
        "errors": len(errors),
        "gate_pass": len(gate_pass),
        "gate_fail": len(success) - len(gate_pass),
        "by_group": by_group,
    }


def decision_summary(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        decision = entry.get("analysis_report", {}).get("decision_report", {})
        action = str(decision.get("action") or "unknown")
        counts[action] = counts.get(action, 0) + 1
    return counts


def render_stage_process() -> str:
    stages = [
        (
            "Stage -1 市场情绪",
            "用 yfinance most_actives 取活跃候选池，再拉 1 年日线。实际参考池不是直接照搬 most_actives，而是按最近 20 日平均成交额重新选 Top200，计算攻击波、回头波、失败攻击、涨跌家数、MA20、新高新低，并做 Top100/Top250 宽窄对比和 SPY/QQQ 状态验证。",
        ),
        (
            "Stage 0 交易池同步",
            "读取或刷新 Bitget RWA 合约池，按股票、ETF、商品分组。这个池子只决定哪些标的可以进入交易分析，不参与市场情绪参考池。",
        ),
        (
            "Stage 1 批量技术扫描",
            "对交易池逐个拉 yfinance 日 K，计算 EMA、ADX、RSI、MACD、ATR、成交量相对强弱，并用 ADX >= 20 且多头排列作为做多 Gate。Bitget 只用于确认该标的是否在交易池。",
        ),
        (
            "Stage 2 基本面摘要",
            "扫描阶段只对 Gate 通过的股票补充 yfinance 基本面摘要，ETF/商品不跑单公司财报叙事，避免把不适用的数据误当成弱基本面。",
        ),
        (
            "Stage 3 单标的深度分析",
            "对 Gate 通过标的跑完整 analyze：基本面叙事、趋势鱼身、逻辑强度、决策矩阵、ATR 风控。这里会重新组合所有模块，给出 enter、small_enter、watch、reject 等动作。",
        ),
        (
            "Stage 4 排名与报告",
            "按是否允许入场、动作优先级、逻辑分、逻辑变化、鱼身位置、延续性、ideal_entry 和仓位倍数排序，最后生成 HTML/JSON，保留完整中间结果便于复核。",
        ),
    ]
    return "\n".join(
        "<div class='stage'>"
        f"<h3>{html.escape(title)}</h3>"
        f"<p>{html.escape(text)}</p>"
        "</div>"
        for title, text in stages
    )


def render_kpi_grid(sentiment: dict[str, Any], trading: dict[str, Any]) -> str:
    sentiment_report = sentiment.get("report") or {}
    sentiment_ref = sentiment_report.get("reference") or {}
    sentiment_quality = sentiment_report.get("data_quality") or {}
    scan_stats = scan_summary(trading.get("scan_results") or [])
    decisions = decision_summary(trading.get("analysis_entries") or [])
    items = [
        ("情绪状态", STATE_LABELS.get(sentiment_report.get("trend", {}).get("state"), "-")),
        ("情绪参考池", f"{sentiment_ref.get('effective_count', '-')}/{sentiment_ref.get('top_n', '-')}"),
        ("OHLCV有效率", fmt_pct(sentiment_quality.get("valid_ratio"))),
        ("交易池", str(len(trading.get("tickers") or []))),
        ("Gate通过", f"{scan_stats['gate_pass']}/{scan_stats['success']}"),
        ("深度分析", str(len(trading.get("analysis_entries") or []))),
        ("允许入场", str(decisions.get("enter", 0) + decisions.get("small_enter", 0))),
        ("扫描错误", str(scan_stats["errors"] + len(trading.get("analysis_errors") or []))),
    ]
    return "\n".join(
        "<div class='metric'>"
        f"<div>{html.escape(label)}</div>"
        f"<strong>{html.escape(value)}</strong>"
        "</div>"
        for label, value in items
    )


def render_sentiment_section(sentiment: dict[str, Any]) -> str:
    report = sentiment.get("report") or {}
    metrics = report.get("metrics") or {}
    trend = report.get("trend") or {}
    ref = report.get("reference") or {}
    score, notes = reliability_score(report)
    rows = [
        ("纯攻击波", fmt_pct(metrics.get("pure_attack_ratio"))),
        ("失败攻击", fmt_pct(metrics.get("failed_attack_ratio"))),
        ("纯回头波", fmt_pct(metrics.get("pure_pullback_ratio"))),
        ("净攻击情绪", fmt_num(metrics.get("net_attack_sentiment"))),
        ("上涨家数", fmt_pct(metrics.get("advance_ratio"))),
        ("20日新低", fmt_pct(metrics.get("low20_ratio"))),
        ("MA20上方", fmt_pct(metrics.get("above_ma20_ratio"))),
        ("净攻击3日斜率", fmt_num(trend.get("net_attack_slope_3"))),
    ]
    compare_rows = []
    for top_n, item in (report.get("breadth_compare") or {}).items():
        state = STATE_LABELS.get(item.get("state"), item.get("state", "-"))
        compare_rows.append(
            "<tr>"
            f"<td>Top{html.escape(str(top_n))}</td>"
            f"<td>{html.escape(str(state))}</td>"
            f"<td>{fmt_num(item.get('net_attack_sentiment'))}</td>"
            f"<td>{fmt_pct(item.get('advance_ratio'))}</td>"
            f"<td>{fmt_pct(item.get('above_ma20_ratio'))}</td>"
            "</tr>"
        )
    note_items = "".join(f"<li>{html.escape(str(note))}</li>" for note in notes)
    return f"""
    <section class='section'>
      <h2>市场情绪</h2>
      <p class='muted'>状态 {html.escape(STATE_LABELS.get(trend.get("state"), str(trend.get("state", "-"))))}，可靠性 {score}/100，候选池 {html.escape(str(ref.get("input_ticker_count", "-")))}，有效参考 {html.escape(str(ref.get("effective_count", "-")))}。</p>
      {f"<ul>{note_items}</ul>" if note_items else ""}
      <table>
        <tbody>
          {"".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(v)}</td></tr>" for k, v in rows)}
        </tbody>
      </table>
      <h3>宽窄对比</h3>
      <table>
        <thead><tr><th>口径</th><th>状态</th><th>净攻击</th><th>上涨家数</th><th>MA20上方</th></tr></thead>
        <tbody>{''.join(compare_rows)}</tbody>
      </table>
    </section>
    """


def render_scan_table(scan_results: list[dict[str, Any]]) -> str:
    sorted_results = sorted(
        scan_results,
        key=lambda item: (
            item.get("status") != "success",
            not bool(item.get("gate_pass")),
            -safe_float(item.get("adx")),
            str(item.get("ticker") or ""),
        ),
    )
    rows = []
    for item in sorted_results:
        if item.get("status") == "error":
            rows.append(
                "<tr>"
                f"<td><strong>{html.escape(str(item.get('ticker', '-')))}</strong></td>"
                "<td colspan='9'>ERROR</td>"
                f"<td>{html.escape(str(item.get('message', '-')))}</td>"
                "</tr>"
            )
            continue
        rows.append(
            "<tr>"
            f"<td><strong>{html.escape(str(item.get('ticker', '-')))}</strong></td>"
            f"<td>{html.escape(GROUP_LABELS.get(str(item.get('group')), str(item.get('group', '-'))))}</td>"
            f"<td>{safe_float(item.get('close')):.2f}</td>"
            f"<td>{safe_float(item.get('change_pct')):+.1f}%</td>"
            f"<td>{html.escape(str(item.get('direction', '-')))}</td>"
            f"<td>{safe_float(item.get('adx')):.1f}</td>"
            f"<td>{safe_float(item.get('rsi')):.0f}</td>"
            f"<td>{html.escape(STAGE_LABELS.get(str(item.get('stage')), str(item.get('stage', '-'))))}</td>"
            f"<td>{html.escape(str(item.get('verdict', '-')))}</td>"
            f"<td>{'PASS' if item.get('gate_pass') else 'FAIL'}</td>"
            f"<td>{html.escape(str(item.get('gate_reason', '-')))}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def render_ranked_cards(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "<p class='muted'>没有 Gate 通过后完成深度分析的标的。</p>"
    cards = []
    for rank, entry in enumerate(entries, start=1):
        report = entry.get("analysis_report") or {}
        decision = report.get("decision_report") or {}
        trend = report.get("trend_report") or {}
        logic = (report.get("logic_report") or {}).get("logic") or {}
        fish = trend.get("fish_body") or {}
        continuation = trend.get("continuation") or {}
        price = trend.get("price") or {}
        risk = report.get("risk_report") or {}
        fundamentals = report.get("fundamentals_report") or {}
        narrative = fundamentals.get("narrative") or {}
        action = str(decision.get("action") or "-")
        drivers = "; ".join(str(item) for item in logic.get("drivers") or []) or "-"
        weaknesses = "; ".join(str(item) for item in logic.get("weaknesses") or []) or "-"
        cards.append(
            "<article class='candidate'>"
            f"<div class='rank'>#{rank}</div>"
            f"<h3>{html.escape(str(report.get('ticker', entry.get('ticker', '-'))))}</h3>"
            f"<div class='action'>{html.escape(ACTION_LABELS.get(action, action))}</div>"
            "<div class='pill-list'>"
            f"<span class='pill'>价格 {safe_float(price.get('close')):.2f}</span>"
            f"<span class='pill'>逻辑 {html.escape(str(logic.get('score', '-')))} / {html.escape(str(logic.get('grade', '-')))}</span>"
            f"<span class='pill'>{html.escape(STAGE_LABELS.get(str(fish.get('stage')), str(fish.get('stage', '-'))))}</span>"
            f"<span class='pill'>延续 {html.escape(str(continuation.get('verdict', '-')))}</span>"
            f"<span class='pill'>仓位 {html.escape(str(decision.get('position_multiplier', '-')))}x</span>"
            "</div>"
            "<table><tbody>"
            f"<tr><th>叙事</th><td>{html.escape(str(narrative.get('thesis', '-')))} / {html.escape(str(narrative.get('score', '-')))}</td></tr>"
            f"<tr><th>Gate</th><td>{html.escape(str((trend.get('gate') or {}).get('reason', '-')))}</td></tr>"
            f"<tr><th>驱动</th><td>{html.escape(drivers)}</td></tr>"
            f"<tr><th>隐忧</th><td>{html.escape(weaknesses)}</td></tr>"
            f"<tr><th>风控</th><td>入场 {safe_float(risk.get('entry')):.2f} / 止损 {safe_float(risk.get('stop')):.2f} / 2R {safe_float((risk.get('targets') or {}).get('2r')):.2f}</td></tr>"
            "</tbody></table>"
            "</article>"
        )
    return "\n".join(cards)


def render_process_summary(trading: dict[str, Any]) -> str:
    scan_stats = scan_summary(trading.get("scan_results") or [])
    counts = group_counts(trading.get("symbols") or [])
    decisions = decision_summary(trading.get("analysis_entries") or [])
    group_text = ", ".join(
        f"{GROUP_LABELS.get(group, group)} {count}"
        for group, count in counts.items()
    )
    decision_text = ", ".join(
        f"{ACTION_LABELS.get(action, action)} {count}"
        for action, count in sorted(decisions.items())
    ) or "-"
    return f"""
    <section class='section'>
      <h2>交易池链路结果</h2>
      <p class='muted'>Bitget 交易池 {len(trading.get("tickers") or [])} 个：{html.escape(group_text)}。</p>
      <div class='pill-list'>
        <span class='pill'>扫描成功 {scan_stats['success']}</span>
        <span class='pill'>Gate通过 {scan_stats['gate_pass']}</span>
        <span class='pill'>Gate失败 {scan_stats['gate_fail']}</span>
        <span class='pill'>扫描错误 {scan_stats['errors']}</span>
        <span class='pill'>深度分析 {len(trading.get("analysis_entries") or [])}</span>
      </div>
      <p class='muted'>决策分布：{html.escape(decision_text)}</p>
    </section>
    """


def render_errors(trading: dict[str, Any]) -> str:
    scan_errors = [
        item for item in trading.get("scan_results") or []
        if item.get("status") == "error"
    ]
    analysis_errors = trading.get("analysis_errors") or []
    if not scan_errors and not analysis_errors:
        return "<p class='muted'>没有错误。</p>"
    rows = []
    for item in scan_errors:
        rows.append(
            "<tr>"
            "<td>scan</td>"
            f"<td>{html.escape(str(item.get('ticker', '-')))}</td>"
            f"<td>{html.escape(str(item.get('message', '-')))}</td>"
            "</tr>"
        )
    for item in analysis_errors:
        rows.append(
            "<tr>"
            "<td>analysis</td>"
            f"<td>{html.escape(str(item.get('ticker', '-')))}</td>"
            f"<td>{html.escape(str(item.get('message', '-')))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>阶段</th><th>标的</th><th>原因</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def render_html(payload: dict[str, Any]) -> str:
    generated_at = payload["generated_at"]
    sentiment = payload["sentiment"]
    trading = payload["trading"]
    ranked = trading.get("ranked") or []
    scan_rows = render_scan_table(trading.get("scan_results") or [])
    timing = trading.get("timing") or {}
    title = f"全链路分析报告 {generated_at[:10]}"
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)}</title>
<style>
  :root {{
    --bg: #101217; --panel: #171b22; --panel2: #202632; --border: #303846;
    --text: #edf2f8; --muted: #9aa7b7; --green: #36c486; --red: #f06b63;
    --amber: #e4b652; --blue: #78aaff; --cyan: #51cad6;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
    line-height: 1.55;
  }}
  main {{ width: min(1280px, calc(100% - 32px)); margin: 0 auto; padding: 30px 0 48px; }}
  h1 {{ margin: 0 0 6px; font-size: 30px; }}
  h2 {{ margin: 28px 0 12px; font-size: 20px; }}
  h3 {{ margin: 0 0 8px; font-size: 16px; }}
  .muted {{ color: var(--muted); }}
  .section, .metric, .stage, .candidate {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
  }}
  .section {{ padding: 16px; margin-top: 12px; }}
  .metrics {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-top: 18px; }}
  .metric {{ padding: 14px; min-height: 86px; }}
  .metric div {{ color: var(--muted); font-size: 13px; }}
  .metric strong {{ display: block; margin-top: 8px; font-size: 24px; }}
  .stages {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }}
  .stage {{ padding: 14px; }}
  .stage p {{ margin: 0; color: var(--muted); }}
  .pill-list {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0; }}
  .pill {{ padding: 4px 8px; border-radius: 999px; background: var(--panel2); color: var(--muted); font-size: 12px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
  th, td {{ padding: 9px 10px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }}
  th {{ color: var(--muted); font-size: 12px; font-weight: 650; background: rgba(255,255,255,0.035); }}
  tr:last-child td {{ border-bottom: 0; }}
  .candidates {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }}
  .candidate {{ padding: 14px; position: relative; }}
  .rank {{ position: absolute; right: 14px; top: 12px; color: var(--cyan); font-weight: 800; }}
  .action {{ display: inline-flex; color: var(--green); font-weight: 720; margin-bottom: 8px; }}
  .scroll {{ overflow-x: auto; }}
  @media (max-width: 900px) {{
    .metrics, .stages, .candidates {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
<main>
  <header>
    <h1>Trading Agent 全链路分析报告</h1>
    <div class="muted">生成时间 {html.escape(generated_at)} · 扫描耗时 {html.escape(str(timing.get("scan_seconds", "-")))}s · 深度分析耗时 {html.escape(str(timing.get("analysis_seconds", "-")))}s</div>
  </header>

  <section class="metrics">
    {render_kpi_grid(sentiment, trading)}
  </section>

  <h2>处理流程</h2>
  <section class="stages">
    {render_stage_process()}
  </section>

  {render_sentiment_section(sentiment)}
  {render_process_summary(trading)}

  <h2>深度分析排名</h2>
  <section class="candidates">
    {render_ranked_cards(ranked)}
  </section>

  <h2>交易池扫描明细</h2>
  <section class="section scroll">
    <table>
      <thead><tr><th>标的</th><th>组</th><th>价格</th><th>涨跌</th><th>方向</th><th>ADX</th><th>RSI</th><th>鱼身</th><th>延续</th><th>Gate</th><th>原因</th></tr></thead>
      <tbody>{scan_rows}</tbody>
    </table>
  </section>

  <h2>错误与降级</h2>
  <section class="section">
    {render_errors(trading)}
  </section>

  <section class="section">
    <strong>边界</strong>
    <p class="muted">这是交易分析报告，不是自动下单。情绪用美股前排参考池，交易目标用 Bitget RWA 交易池；全部行情/K线来自 yfinance。商品没有财报叙事，基本面阶段会自动弱化或跳过。</p>
  </section>
</main>
</body>
</html>
"""


def build_full_chain_payload(args: argparse.Namespace) -> dict[str, Any]:
    generated_at = datetime.now().isoformat(timespec="seconds")
    print("Stage -1: running market sentiment...", flush=True)
    sentiment = run_sentiment(args)
    print("Stage 0-4: running Bitget trading chain...", flush=True)
    trading = run_trading_chain(args)
    return {
        "status": "success",
        "generated_at": generated_at,
        "args": vars(args),
        "sentiment": sentiment,
        "trading": trading,
    }


def parse_int_list(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成 Trading Agent 全链路 HTML 报告")
    parser.add_argument("--group", default="all",
                        choices=["all", "stock", "etf", "commodity", "mega_cap"],
                        help="交易池扫描分组")
    parser.add_argument("--force-sync", action="store_true",
                        help="强制刷新 Bitget 品种池")
    parser.add_argument("--scan-delay", type=float, default=0.2,
                        help="交易池扫描每个标的间隔秒数")
    parser.add_argument("--days", type=int, default=90,
                        help="Bitget 技术分析回看天数")
    parser.add_argument("--account", type=float, default=100000,
                        help="账户资金")
    parser.add_argument("--risk-pct", type=float, default=0.02,
                        help="基础单笔风险比例")
    parser.add_argument("--sentiment-candidates", type=int, default=350,
                        help="yfinance most_actives 候选数量")
    parser.add_argument("--sentiment-top", type=int, default=200,
                        help="情绪参考池 TopN")
    parser.add_argument("--sentiment-compare", type=parse_int_list, default=[100, 250],
                        help="情绪宽窄对比，如 100,250")
    parser.add_argument("--sentiment-period", default="1y",
                        help="情绪 OHLCV 周期")
    parser.add_argument("--sentiment-chunk-size", type=int, default=60,
                        help="情绪 yfinance 分块大小")
    parser.add_argument("--sentiment-retries", type=int, default=2,
                        help="情绪 yfinance 重试次数")
    parser.add_argument("--sentiment-retry-sleep", type=float, default=1.0,
                        help="情绪 yfinance 重试间隔")
    parser.add_argument("--use-sentiment-cache", action="store_true",
                        help="使用已有 yfinance 情绪价格缓存")
    parser.add_argument("--output-dir", default=str(ROOT / "reports"),
                        help="报告输出目录")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_full_chain_payload(args)
    generated_date = payload["generated_at"][:10].replace("-", "")
    stem = f"full_chain_report_{generated_date}"
    html_text = render_html(payload)
    html_path, json_path = write_files(Path(args.output_dir), stem, payload, html_text)
    print(f"Wrote HTML: {html_path}")
    print(f"Wrote JSON: {json_path}")


if __name__ == "__main__":
    main()
