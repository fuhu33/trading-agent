"""批量扫描模块

对多个 Bitget RWA 品种批量运行趋势分析，输出汇总表格，筛选 Gate 通过的标的。

用法 (CLI):
    uv run trading-agent scan AAPL,MSFT,NVDA       # 指定品种
    uv run trading-agent scan --group mega_cap      # 按分组扫描
    uv run trading-agent scan --with-fund           # 含基本面
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone

from .symbols import get_symbols
from .trend import build_trend_report
from .fundamentals import build_fundamentals_report, flush_cache

# ---------------------------------------------------------------------------
# 预定义分组
# ---------------------------------------------------------------------------

MEGA_CAP = {"AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"}

GROUP_CHOICES = ["all", "stock", "etf", "commodity", "mega_cap"]

# ---------------------------------------------------------------------------
# 方向/动能中文映射
# ---------------------------------------------------------------------------

DIRECTION_MAP = {"bullish": "多头", "bearish": "空头", "neutral": "震荡"}
MOMENTUM_MAP = {"accelerating": "扩张", "decelerating": "收缩", "flat": "横盘"}
STAGE_MAP = {"early": "鱼头", "mid": "鱼身", "late": "鱼尾", "n/a": "-"}
THESIS_MAP = {"strong": "强", "moderate": "中", "weak": "弱"}


# ---------------------------------------------------------------------------
# 核心逻辑
# ---------------------------------------------------------------------------

def resolve_tickers(tickers_csv: str | None, group: str) -> list[str]:
    """解析要扫描的品种列表

    优先使用逗号分隔的 ticker 参数；否则按 group 从品种缓存获取。
    """
    if tickers_csv:
        return [t.strip().upper() for t in tickers_csv.split(",") if t.strip()]

    report = get_symbols()
    symbols = report["symbols"]

    if group == "mega_cap":
        return sorted([s["baseCoin"] for s in symbols if s["baseCoin"] in MEGA_CAP])
    elif group != "all":
        return [s["baseCoin"] for s in symbols if s["group"] == group]
    else:
        return [s["baseCoin"] for s in symbols]


def scan_single(ticker: str, with_fund: bool = False) -> dict:
    """扫描单个品种，返回摘要或错误

    with_fund=True 时额外拉取基本面 (在技术面 Gate 通过后才拉, 节省调用)
    """
    try:
        report = build_trend_report(ticker)
        result = {
            "status": "success",
            "ticker": ticker,
            "group": report["group"],
            "close": report["price"]["close"],
            "change_pct": report["price"]["change_pct"],
            "direction": report["trend"]["direction"],
            "strength": report["trend"]["strength"],
            "adx": report["trend"]["adx"],
            "rsi": report["raw"]["rsi"],
            "macd_hist": report["raw"]["macd_hist"],
            "momentum": report["continuation"]["momentum"],
            "volume_ratio": report["continuation"]["volume_ratio"],
            "verdict": report["continuation"]["verdict"],
            "risk_flags": report["continuation"]["risk_flags"],
            "stage": report["fish_body"]["stage"],
            "trend_age_days": report["fish_body"]["trend_age_days"],
            "cumulative_pct": report["fish_body"]["cumulative_pct"],
            "deviation_pct": report["fish_body"]["deviation_pct"],
            "ideal_entry": report["fish_body"]["ideal_entry"],
            "gate_pass": report["gate"]["pass"],
            "gate_reason": report["gate"]["reason"],
        }

        # 仅对通过 Gate 的股票拉基本面；ETF/商品没有单公司财报叙事。
        if with_fund and result["gate_pass"] and result["group"] == "stock":
            try:
                fund = build_fundamentals_report(ticker)
                if fund.get("status") == "success":
                    n = fund.get("narrative", {})
                    a = fund.get("analysts") or {}
                    s = fund.get("sector") or {}
                    e_ = fund.get("next_earnings") or {}
                    result["narrative_score"] = n.get("score")
                    result["thesis"] = n.get("thesis")
                    result["earnings_catalyst"] = n.get("earnings_catalyst", False)
                    result["upside_pct"] = a.get("upside_pct")
                    result["sector_trend"] = s.get("trend")
                    result["earnings_in_window"] = e_.get("in_window", False)
                    result["days_to_earnings"] = e_.get("days_until")
            except Exception as fund_err:
                result["fund_error"] = str(fund_err)

        return result
    except Exception as e:
        return {
            "status": "error",
            "ticker": ticker,
            "message": str(e),
        }


def scan_batch(tickers: list[str], delay: float = 1.5,
               with_fund: bool = False) -> list[dict]:
    """批量扫描，返回结果列表"""
    results = []
    total = len(tickers)

    for i, ticker in enumerate(tickers):
        progress = f"[{i + 1}/{total}]"
        print(f"{progress} 扫描 {ticker} ...", file=sys.stderr, flush=True)

        result = scan_single(ticker, with_fund=with_fund)
        results.append(result)

        if result["status"] == "error":
            print(f"{progress} {ticker}: 错误 - {result['message']}", file=sys.stderr)

        # 请求间隔，避免 Bitget API 限流
        if i < total - 1:
            time.sleep(delay)

    # 批量扫描结束后统一落盘缓存
    if with_fund:
        flush_cache()

    return results


# ---------------------------------------------------------------------------
# 输出格式
# ---------------------------------------------------------------------------

def format_table(results: list[dict], with_fund: bool = False) -> str:
    """格式化为 Markdown 汇总表格"""
    lines = []

    # 表头 - 随 with_fund 变化
    if with_fund:
        lines.append(
            "| 品种 | 价格 | 涨跌% | 趋势 | ADX | RSI | 动能 | 量比 | 鱼身 | 延续 | 叙事 | 上涨空间 | 财报 | Gate |"
        )
        lines.append(
            "|------|------|-------|------|-----|-----|------|------|------|------|------|------|------|------|"
        )
    else:
        lines.append(
            "| 品种 | 价格 | 涨跌% | 趋势 | ADX | RSI | 动能 | 量比 | 鱼身 | 延续 | 风险 | Gate |"
        )
        lines.append(
            "|------|------|-------|------|-----|-----|------|------|------|------|------|------|"
        )

    passed = []
    failed = []
    errors = []

    for r in results:
        if r["status"] == "error":
            errors.append(r)
            if with_fund:
                lines.append(f"| {r['ticker']} | - | - | ERROR | - | - | - | - | - | - | - | - | - | - |")
            else:
                lines.append(f"| {r['ticker']} | - | - | ERROR | - | - | - | - | - | - | - | - |")
            continue

        direction_zh = DIRECTION_MAP.get(r["direction"], r["direction"])
        momentum_zh = MOMENTUM_MAP.get(r["momentum"], r["momentum"])
        stage_zh = STAGE_MAP.get(r.get("stage", "n/a"), "-")
        gate_str = "✅" if r["gate_pass"] else "❌"
        risk_str = ",".join(r["risk_flags"]) if r["risk_flags"] else "-"

        if r.get("ideal_entry"):
            stage_zh = f"⭐{stage_zh}"

        base = (
            f"| {r['ticker']}"
            f" | {r['close']}"
            f" | {r['change_pct']:+.1f}%"
            f" | {direction_zh}/{r['strength'][:1].upper()}"
            f" | {r['adx']:.1f}"
            f" | {r['rsi']:.0f}"
            f" | {momentum_zh}"
            f" | {r['volume_ratio']:.1f}x"
            f" | {stage_zh}"
            f" | {r['verdict']}"
        )

        if with_fund:
            thesis_zh = THESIS_MAP.get(r.get("thesis"), "-")
            score = r.get("narrative_score")
            score_str = f"{thesis_zh}({score})" if score is not None else "-"
            upside = r.get("upside_pct")
            upside_str = f"{upside:+.1f}%" if upside is not None else "-"
            if r.get("earnings_catalyst"):
                earnings_str = f"🚀{r.get('days_to_earnings')}d"
            elif r.get("earnings_in_window"):
                earnings_str = f"⚠️{r.get('days_to_earnings')}d"
            elif r.get("days_to_earnings"):
                earnings_str = f"{r.get('days_to_earnings')}d"
            else:
                earnings_str = "-"
            line = base + f" | {score_str} | {upside_str} | {earnings_str} | {gate_str} |"
        else:
            line = base + f" | {risk_str} | {gate_str} |"

        lines.append(line)

        if r["gate_pass"]:
            passed.append(r)
        else:
            failed.append(r)

    # 汇总
    lines.append("")
    lines.append(f"**扫描完成**: {len(results)} 品种, "
                 f"通过 {len(passed)}, 未通过 {len(failed)}, 错误 {len(errors)}")

    if passed:
        tickers_str = ", ".join(r["ticker"] for r in passed)
        lines.append(f"**Gate 通过**: {tickers_str}")

        if with_fund:
            star_picks = [
                r for r in passed
                if r.get("thesis") == "strong"
                and r.get("stage") in ("early", "mid")
                and r.get("verdict") == "strong"
                and not r.get("earnings_in_window")
            ]
            if star_picks:
                tk_list = ", ".join(
                    f"{r['ticker']}(叙事{r.get('narrative_score')}/10, {STAGE_MAP.get(r['stage'])})"
                    for r in star_picks
                )
                lines.append("")
                lines.append(f"**⭐ 三层共振 (基本面强 + 鱼身位置 + 动力强)**: {tk_list}")

            catalyst_picks = [
                r for r in passed
                if r.get("earnings_catalyst")
                and r.get("stage") in ("early", "mid")
            ]
            if catalyst_picks:
                tk_list = ", ".join(
                    f"{r['ticker']}(叙事{r.get('narrative_score')}/10, {STAGE_MAP.get(r['stage'])}, {r.get('days_to_earnings')}天后财报)"
                    for r in catalyst_picks
                )
                lines.append("")
                lines.append(f"**🚀 财报催化剂先手 (强叙事 + 好位置 + 财报窗口)**: {tk_list}")

    return "\n".join(lines)


def build_json_report(results: list[dict]) -> dict:
    """构建 JSON 格式汇总报告"""
    passed = [r for r in results if r.get("gate_pass")]
    failed = [r for r in results if r.get("status") == "success" and not r.get("gate_pass")]
    errors = [r for r in results if r.get("status") == "error"]

    return {
        "status": "success",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(results),
            "passed": len(passed),
            "failed": len(failed),
            "errors": len(errors),
        },
        "passed_tickers": [r["ticker"] for r in passed],
        "results": results,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="批量扫描 Bitget RWA 品种趋势"
    )
    parser.add_argument("tickers", nargs="?", default=None,
                        help="逗号分隔的品种代码 (如 AAPL,MSFT,NVDA)")
    parser.add_argument("--group", choices=GROUP_CHOICES, default="all",
                        help="按分组扫描 (默认: all)")
    parser.add_argument("--delay", type=float, default=1.5,
                        help="请求间隔秒数 (默认: 1.5)")
    parser.add_argument("--json", action="store_true",
                        help="输出 JSON 格式 (默认: Markdown 表格)")
    parser.add_argument("--with-fund", action="store_true",
                        help="对 Gate 通过品种额外拉取基本面 (慢但更准)")
    args = parser.parse_args()

    tickers = resolve_tickers(args.tickers, args.group)

    if not tickers:
        print(json.dumps({"status": "error", "message": "无品种可扫描"}),
              file=sys.stdout)
        sys.exit(1)

    print(f"即将扫描 {len(tickers)} 个品种 (delay={args.delay}s) ...",
          file=sys.stderr, flush=True)

    results = scan_batch(tickers, delay=args.delay, with_fund=args.with_fund)

    if args.json:
        report = build_json_report(results)
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_table(results, with_fund=args.with_fund))


if __name__ == "__main__":
    main()
