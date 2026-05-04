"""Generate a latest US stock sentiment HTML report."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from trading_agent.sentiment import build_market_sentiment_report  # noqa: E402


STATE_LABELS = {
    "RISK_OFF": "退潮",
    "COLD": "冰点",
    "RECOVERY_CANDIDATE": "回暖候选",
    "RISK_ON": "强势",
    "DIVERGENCE": "分歧",
}

STATE_NOTES = {
    "RISK_OFF": "攻击弱、回头强，风险偏好仍在收缩。",
    "COLD": "弱势或恐慌特征较重，适合作为后续回暖观察起点。",
    "RECOVERY_CANDIDATE": "近期经历冰点后，攻击、广度或均线修复开始转暖。",
    "RISK_ON": "攻击和广度同步占优，市场风险偏好较强。",
    "DIVERGENCE": "核心指标不同步，说明情绪正在拉扯，适合降低结论权重。",
}

METRIC_LABELS = {
    "pure_attack_ratio": "纯攻击波",
    "failed_attack_ratio": "失败攻击",
    "pure_pullback_ratio": "纯回头波",
    "net_attack_sentiment": "净攻击情绪",
    "advance_ratio": "上涨家数占比",
    "up_dollar_volume_ratio": "上涨成交额占比",
    "high20_ratio": "20日新高占比",
    "low20_ratio": "20日新低占比",
    "above_ma20_ratio": "MA20上方占比",
    "attack_quality": "攻击质量",
    "attack_failure_rate": "攻击失败率",
    "reclaim_ma20_ratio": "收复MA20",
    "lose_ma20_ratio": "跌破MA20",
}


def disable_yfinance_sqlite_cache() -> None:
    """Avoid yfinance sqlite cache writes in restricted local workspaces."""
    try:
        import yfinance.cache as yf_cache

        yf_cache._CookieCacheManager._Cookie_cache = yf_cache._CookieCacheDummy()
        yf_cache._TzCacheManager._tz_cache = yf_cache._TzCacheDummy()
    except Exception:
        return


def make_yfinance_session() -> Any | None:
    try:
        from curl_cffi import requests as curl_requests

        return curl_requests.Session(impersonate="chrome")
    except Exception:
        return None


def fetch_most_active_quotes(candidate_count: int) -> list[dict[str, Any]]:
    import yfinance as yf

    disable_yfinance_sqlite_cache()
    session = make_yfinance_session()
    quotes: list[dict[str, Any]] = []
    offset = 0
    page_size = min(250, max(1, candidate_count))
    while len(quotes) < candidate_count:
        payload = yf.screen(
            "most_actives",
            offset=offset,
            size=min(page_size, candidate_count - len(quotes)),
            session=session,
        )
        page = payload.get("quotes", []) if isinstance(payload, dict) else []
        if not page:
            break
        quotes.extend(dict(item) for item in page if isinstance(item, dict))
        total = int(payload.get("total", 0) or 0) if isinstance(payload, dict) else 0
        offset += len(page)
        if total and offset >= total:
            break
    return quotes


def normalize_symbol(symbol: Any) -> str:
    text = str(symbol).strip().upper()
    return text if re.fullmatch(r"[A-Z0-9.\-]+", text) else ""


def quote_symbol(quote: dict[str, Any]) -> str:
    return normalize_symbol(quote.get("symbol") or quote.get("ticker") or "")


def quote_volume(quote: dict[str, Any]) -> int:
    value = quote.get("regularMarketVolume") or quote.get("dayvolume") or 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def quote_price(quote: dict[str, Any]) -> float:
    value = quote.get("regularMarketPrice") or quote.get("intradayprice") or 0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def collect_candidate_symbols(candidate_count: int) -> tuple[list[str], list[dict[str, Any]]]:
    quotes = fetch_most_active_quotes(candidate_count)
    symbols: list[str] = []
    seen: set[str] = set()
    clean_quotes: list[dict[str, Any]] = []
    for quote in quotes:
        symbol = quote_symbol(quote)
        if not symbol or symbol in seen:
            continue
        quote_type = str(quote.get("quoteType") or "").upper()
        if quote_type and quote_type != "EQUITY":
            continue
        seen.add(symbol)
        symbols.append(symbol)
        clean_quotes.append(quote)
    return symbols, clean_quotes


def json_default(value: Any) -> Any:
    try:
        import numpy as np
        import pandas as pd

        if isinstance(value, (np.integer, np.floating)):
            return value.item()
        if isinstance(value, np.bool_):
            return bool(value)
        if isinstance(value, pd.Timestamp):
            return value.strftime("%Y-%m-%d")
        if pd.isna(value):
            return None
    except Exception:
        pass
    return str(value)


def fmt_pct(value: Any) -> str:
    try:
        if value is None:
            return "n/a"
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def fmt_num(value: Any) -> str:
    try:
        if value is None:
            return "n/a"
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "n/a"


def fmt_volume(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if number >= 1_000_000_000:
        return f"{number / 1_000_000_000:.1f}B"
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"{number / 1_000:.1f}K"
    return f"{number:.0f}"


def reliability_score(report: dict[str, Any]) -> tuple[int, list[str]]:
    score = 100
    reasons: list[str] = []
    reference = report.get("reference", {})
    quality = report.get("data_quality", {})
    top_n = int(reference.get("top_n") or 0)
    effective = int(reference.get("effective_count") or 0)
    input_count = int(reference.get("input_ticker_count") or 0)
    valid_ratio = float(quality.get("valid_ratio") or 0)

    if effective < top_n:
        gap = top_n - effective
        score -= min(25, gap)
        reasons.append(f"有效样本 {effective}/{top_n}，少于目标参考池。")
    if input_count < top_n * 1.2:
        score -= 10
        reasons.append("候选池冗余不足，个别缺失数据会放大样本偏差。")
    if valid_ratio < 0.98:
        score -= int((0.98 - valid_ratio) * 100)
        reasons.append(f"OHLCV 有效率 {valid_ratio:.1%}，存在缺失或异常。")
    if report.get("status") == "partial":
        score -= 8
        reasons.append("数据源返回 partial，需要降低结论权重。")
    if report.get("trend", {}).get("state") == "DIVERGENCE":
        score -= 8
        reasons.append("当前为分歧态，方向判断天然低于单边状态。")

    return max(0, min(100, score)), reasons


def metric_tiles(report: dict[str, Any]) -> str:
    metrics = report.get("metrics", {})
    items = []
    for key in [
        "pure_attack_ratio",
        "failed_attack_ratio",
        "pure_pullback_ratio",
        "net_attack_sentiment",
        "advance_ratio",
        "low20_ratio",
        "above_ma20_ratio",
        "attack_quality",
    ]:
        value = metrics.get(key)
        text = fmt_num(value) if key == "net_attack_sentiment" else fmt_pct(value)
        items.append(
            "<div class='metric'>"
            f"<div>{html.escape(METRIC_LABELS[key])}</div>"
            f"<strong>{html.escape(text)}</strong>"
            "</div>"
        )
    return "\n".join(items)


def compare_table(report: dict[str, Any]) -> str:
    rows = []
    for top_n, item in report.get("breadth_compare", {}).items():
        state = item.get("state", "n/a")
        rows.append(
            "<tr>"
            f"<td>Top{html.escape(str(top_n))}</td>"
            f"<td>{html.escape(STATE_LABELS.get(state, state))}</td>"
            f"<td>{fmt_num(item.get('net_attack_sentiment'))}</td>"
            f"<td>{fmt_pct(item.get('advance_ratio'))}</td>"
            f"<td>{fmt_pct(item.get('low20_ratio'))}</td>"
            f"<td>{fmt_pct(item.get('above_ma20_ratio'))}</td>"
            f"<td>{html.escape(str(item.get('effective_count', 'n/a')))}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def validation_table(report: dict[str, Any]) -> str:
    validation = report.get("validation")
    if not isinstance(validation, dict) or validation.get("status") != "success":
        return "<p class='muted'>本次未生成历史验证样本。</p>"

    rows = []
    for benchmark, data in validation.get("benchmarks", {}).items():
        for state, horizons in data.get("states", {}).items():
            for horizon, stats in horizons.items():
                rows.append(
                    "<tr>"
                    f"<td>{html.escape(benchmark)}</td>"
                    f"<td>{html.escape(STATE_LABELS.get(state, state))}</td>"
                    f"<td>{html.escape(horizon)}</td>"
                    f"<td>{fmt_pct(stats.get('mean'))}</td>"
                    f"<td>{fmt_pct(stats.get('median'))}</td>"
                    f"<td>{fmt_pct(stats.get('hit_rate'))}</td>"
                    f"<td>{html.escape(str(stats.get('count', 'n/a')))}</td>"
                    "</tr>"
                )
    return "\n".join(rows) or "<tr><td colspan='7'>无有效验证样本</td></tr>"


def quote_table(quotes: list[dict[str, Any]], limit: int = 30) -> str:
    rows = []
    for quote in quotes[:limit]:
        symbol = quote_symbol(quote)
        name = quote.get("shortName") or quote.get("longName") or quote.get("companyshortname") or ""
        price = quote_price(quote)
        volume = quote_volume(quote)
        rows.append(
            "<tr>"
            f"<td><strong>{html.escape(symbol)}</strong></td>"
            f"<td>{html.escape(str(name))}</td>"
            f"<td>{price:.2f}</td>"
            f"<td>{fmt_volume(volume)}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def render_html(report: dict[str, Any], quotes: list[dict[str, Any]],
                generated_at: datetime) -> str:
    reference = report.get("reference", {})
    trend = report.get("trend", {})
    quality = report.get("data_quality", {})
    state = trend.get("state", "n/a")
    score, score_notes = reliability_score(report)
    selected = reference.get("selected_tickers", [])
    selected_preview = ", ".join(str(item) for item in selected[:80])
    if len(selected) > 80:
        selected_preview += f" ... (+{len(selected) - 80})"
    warnings = report.get("warnings") or []
    warning_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in warnings + score_notes)
    state_label = STATE_LABELS.get(state, state)
    state_note = STATE_NOTES.get(state, "暂无状态说明。")
    title = f"美股情绪报告 {report.get('date', 'n/a')}"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)}</title>
<style>
  :root {{
    --bg: #0f1115; --panel: #171a21; --panel2: #1f2430; --border: #303744;
    --text: #ecf1f8; --muted: #9aa6b5; --green: #33c481; --red: #ef6461;
    --amber: #e7b84d; --blue: #72a7ff; --cyan: #52c7d8;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
    line-height: 1.55;
  }}
  main {{ width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 28px 0 42px; }}
  header {{ display: grid; grid-template-columns: 1fr auto; gap: 18px; align-items: end; margin-bottom: 22px; }}
  h1 {{ margin: 0 0 6px; font-size: 28px; font-weight: 720; }}
  h2 {{ margin: 26px 0 12px; font-size: 18px; }}
  .muted {{ color: var(--muted); }}
  .badge {{
    display: inline-flex; align-items: center; gap: 8px; padding: 7px 11px;
    border: 1px solid var(--border); border-radius: 999px; background: var(--panel2);
    font-weight: 650;
  }}
  .score {{ text-align: right; }}
  .score strong {{ font-size: 30px; color: var(--cyan); }}
  .grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }}
  .metric, .section {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
  }}
  .metric {{ padding: 14px; min-height: 86px; }}
  .metric div {{ color: var(--muted); font-size: 13px; }}
  .metric strong {{ display: block; margin-top: 8px; font-size: 24px; }}
  .section {{ padding: 16px; margin-top: 12px; }}
  table {{ width: 100%; border-collapse: collapse; overflow: hidden; border-radius: 8px; }}
  th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); text-align: left; }}
  th {{ color: var(--muted); font-size: 12px; font-weight: 650; background: rgba(255,255,255,0.035); }}
  tr:last-child td {{ border-bottom: 0; }}
  .state-note {{ color: var(--muted); margin-top: 8px; }}
  .pill-list {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }}
  .pill {{ padding: 4px 8px; border-radius: 999px; background: var(--panel2); color: var(--muted); font-size: 12px; }}
  ul {{ margin: 8px 0 0; padding-left: 18px; color: var(--muted); }}
  code {{ color: var(--blue); }}
  @media (max-width: 860px) {{
    header {{ grid-template-columns: 1fr; }}
    .score {{ text-align: left; }}
    .grid {{ grid-template-columns: repeat(2, 1fr); }}
  }}
  @media (max-width: 560px) {{
    .grid {{ grid-template-columns: 1fr; }}
    th, td {{ padding: 8px; font-size: 13px; }}
  }}
</style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>美股情绪分析报告</h1>
      <div class="muted">报告日期 {html.escape(str(report.get("date", "n/a")))} · 生成时间 {generated_at.strftime("%Y-%m-%d %H:%M:%S")} · 数据源 yfinance most_actives + OHLCV</div>
    </div>
    <div class="score">
      <div class="muted">参考可靠性</div>
      <strong>{score}</strong><span class="muted"> / 100</span>
    </div>
  </header>

  <section class="section">
    <div class="badge">当前状态：{html.escape(state_label)} <span class="muted">({html.escape(str(state))})</span></div>
    <div class="state-note">{html.escape(state_note)}</div>
    <div class="pill-list">
      <span class="pill">候选池 {html.escape(str(reference.get("input_ticker_count", "n/a")))}</span>
      <span class="pill">目标 Top{html.escape(str(reference.get("top_n", "n/a")))}</span>
      <span class="pill">有效样本 {html.escape(str(reference.get("effective_count", "n/a")))}</span>
      <span class="pill">OHLCV有效率 {fmt_pct(quality.get("valid_ratio"))}</span>
    </div>
    {f"<ul>{warning_html}</ul>" if warning_html else ""}
  </section>

  <h2>核心指标</h2>
  <section class="grid">
    {metric_tiles(report)}
  </section>

  <h2>宽窄对比</h2>
  <section class="section">
    <table>
      <thead><tr><th>口径</th><th>状态</th><th>净攻击</th><th>上涨占比</th><th>20日新低</th><th>MA20上方</th><th>有效样本</th></tr></thead>
      <tbody>{compare_table(report)}</tbody>
    </table>
  </section>

  <h2>历史验证</h2>
  <section class="section">
    <table>
      <thead><tr><th>基准</th><th>状态</th><th>周期</th><th>均值</th><th>中位数</th><th>胜率</th><th>样本</th></tr></thead>
      <tbody>{validation_table(report)}</tbody>
    </table>
  </section>

  <h2>参考池复核</h2>
  <section class="section">
    <div class="muted">实际 Top{html.escape(str(reference.get("top_n", "n/a")))} 由最近 {html.escape(str(reference.get("lookback_days", "n/a")))} 个交易日平均成交额从候选池中选择。</div>
    <p>{html.escape(selected_preview) if selected_preview else "n/a"}</p>
  </section>

  <h2>yfinance Most Actives 候选前排</h2>
  <section class="section">
    <table>
      <thead><tr><th>Ticker</th><th>名称</th><th>价格</th><th>日成交量</th></tr></thead>
      <tbody>{quote_table(quotes)}</tbody>
    </table>
  </section>

  <section class="section">
    <strong>读法提示</strong>
    <p class="muted">这个报告是情绪温度计，不是入场信号。重点看状态是否从冰点向回暖候选迁移，以及纯攻击波、回头波、上涨家数、MA20 修复是否同步改善。若状态为分歧，说明部分大票或部分广度指标互相打架，应降低仓位或等待二次确认。</p>
  </section>
</main>
</body>
</html>
"""


def write_report_files(output_dir: Path, date_part: str, payload: dict[str, Any],
                       html_text: str) -> tuple[Path, Path]:
    html_path = output_dir / f"us_stock_sentiment_{date_part}.html"
    json_path = output_dir / f"us_stock_sentiment_{date_part}.json"
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
        fallback.mkdir(parents=True, exist_ok=True)
        return write_report_files(fallback, date_part, payload, html_text)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成最新美股情绪 HTML 报告")
    parser.add_argument("--candidate-count", type=int, default=350,
                        help="从 yfinance most_actives 拉取的候选数量")
    parser.add_argument("--top", type=int, default=200, help="主参考池 TopN")
    parser.add_argument("--compare", default="100,250",
                        help="宽窄对比口径，逗号分隔")
    parser.add_argument("--period", default="1y", help="OHLCV 拉取周期")
    parser.add_argument("--chunk-size", type=int, default=60,
                        help="每批 yfinance 下载 ticker 数")
    parser.add_argument("--retries", type=int, default=2, help="每批重试次数")
    parser.add_argument("--retry-sleep", type=float, default=1.0,
                        help="重试间隔秒数")
    parser.add_argument("--benchmarks", default="SPY,QQQ",
                        help="历史验证基准，逗号分隔")
    parser.add_argument("--forward", default="1,3,5",
                        help="历史验证 forward days，逗号分隔")
    parser.add_argument("--output-dir", default=str(ROOT / "reports"),
                        help="报告输出目录")
    parser.add_argument("--use-cache", action="store_true",
                        help="使用已有 yfinance OHLCV CSV 缓存")
    return parser.parse_args()


def parse_ints(value: str) -> tuple[int, ...]:
    return tuple(int(item.strip()) for item in value.split(",") if item.strip())


def parse_symbols(value: str) -> tuple[str, ...]:
    return tuple(item.strip().upper() for item in value.split(",") if item.strip())


def main() -> None:
    args = parse_args()
    disable_yfinance_sqlite_cache()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Fetching yfinance most_actives candidates: {args.candidate_count}")
    tickers, quotes = collect_candidate_symbols(args.candidate_count)
    if len(tickers) < args.top:
        raise RuntimeError(
            f"candidate pool too small: {len(tickers)} symbols for Top{args.top}"
        )

    print(f"Running sentiment report: candidates={len(tickers)} top={args.top}")
    report = build_market_sentiment_report(
        tickers,
        top_n=args.top,
        compare_top_n=parse_ints(args.compare),
        period=args.period,
        chunk_size=args.chunk_size,
        retries=args.retries,
        retry_sleep=args.retry_sleep,
        use_cache=args.use_cache,
        refresh_cache=not args.use_cache,
        validate=True,
        benchmark_tickers=parse_symbols(args.benchmarks),
        forward_days=parse_ints(args.forward),
    )
    if report.get("status") == "error":
        raise RuntimeError(str(report.get("message", "unknown report error")))

    generated_at = datetime.now()
    date_part = str(report.get("date") or generated_at.strftime("%Y-%m-%d")).replace("-", "")
    payload = {
        "report": report,
        "candidate_tickers": tickers,
        "candidate_quotes": quotes,
        "generated_at": generated_at.isoformat(timespec="seconds"),
    }
    html_path, json_path = write_report_files(
        output_dir,
        date_part,
        payload,
        render_html(report, quotes, generated_at),
    )
    print(f"Wrote HTML: {html_path}")
    print(f"Wrote JSON: {json_path}")


if __name__ == "__main__":
    main()
