"""Markdown report rendering for structured analysis results."""

from __future__ import annotations


def _fmt_pct(value: float | int | None, digits: int = 2) -> str:
    if value is None:
        return "-"
    return f"{float(value):.{digits}f}%"


def _fmt_money(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"${float(value):.2f}"


def _fmt_adjustment(adjustment: object) -> str:
    if not isinstance(adjustment, dict):
        return str(adjustment)

    name = adjustment.get("name", "adjustment")
    factor = adjustment.get("factor")
    reason = adjustment.get("reason")

    parts = [str(name)]
    if factor is not None:
        parts.append(f"factor={factor}")
    if reason:
        parts.append(str(reason))
    return " (" + ", ".join(parts) + ")"


def render_analysis_markdown(report: dict) -> str:
    """Render an AnalysisReport into a compact Markdown report."""
    ticker = report.get("ticker", "-")
    if report.get("status") not in {"success", "degraded"}:
        message = report.get("message", "分析失败")
        return f"## {ticker} 波段分析\n\n**状态**: {message}"

    trend_report = report.get("trend_report", {})
    logic_report = report.get("logic_report", {})
    decision = report.get("decision_report", {})
    risk = report.get("risk_report")

    logic = logic_report.get("logic", {})
    fish = trend_report.get("fish_body", {})
    continuation = trend_report.get("continuation", {})
    levels = trend_report.get("levels", {})
    price = trend_report.get("price", {})

    action_label = decision.get("action_label", decision.get("action", "-"))
    multiplier = decision.get("position_multiplier", 0)
    final_risk_pct = decision.get("final_risk_pct")
    warnings = report.get("warnings") or []

    lines = [
        f"## {ticker} 波段分析",
        "",
        f"**当前结论**: {action_label}",
    ]

    if warnings:
        lines.extend(["", "**状态**: 数据降级，部分模块不可用"])

    lines.extend([
        "",
        "### 核心状态",
        "",
        f"- **价格**: {_fmt_money(price.get('close'))} ({price.get('change_pct', 0):+.2f}%)",
        f"- **趋势 Gate**: {'PASS' if trend_report.get('gate', {}).get('pass') else 'FAIL'} - {trend_report.get('gate', {}).get('reason', '-')}",
        f"- **逻辑强度**: {logic.get('score', '-')} / {logic.get('grade', '-')}，变化 {logic.get('trend', '-')} ({logic.get('delta', '-')})",
        f"- **鱼身阶段**: {fish.get('stage', '-')}，ideal_entry={fish.get('ideal_entry', '-')}",
        f"- **趋势持续性**: {continuation.get('verdict', '-')}，量比 {continuation.get('volume_ratio', '-')}x",
        "",
        "### 决策",
        "",
        f"- **动作**: {decision.get('action', '-')}",
        f"- **仓位倍数**: {multiplier}x",
        f"- **最终单笔风险**: {_fmt_pct(final_risk_pct * 100 if isinstance(final_risk_pct, float) and final_risk_pct <= 1 else final_risk_pct)}",
    ])

    reasons = decision.get("reasons") or []
    if reasons:
        lines.append(f"- **理由**: {'; '.join(reasons)}")

    adjustments = decision.get("adjustments") or []
    if adjustments:
        lines.append(f"- **调整因子**: {'; '.join(_fmt_adjustment(item) for item in adjustments)}")

    if warnings:
        lines.extend(["", "### 数据提示", ""])
        for warning in warnings:
            if isinstance(warning, dict):
                component = warning.get("component", "component")
                message = warning.get("message", "unknown error")
                lines.append(f"- **{component}**: {message}")
            else:
                lines.append(f"- {warning}")

    drivers = logic.get("drivers") or []
    weaknesses = logic.get("weaknesses") or []
    lines.extend(["", "### 逻辑强度", ""])
    lines.append(f"- **驱动**: {'; '.join(drivers) if drivers else '-'}")
    lines.append(f"- **隐忧**: {'; '.join(weaknesses) if weaknesses else '-'}")

    lines.extend(["", "### 关键价位", ""])
    lines.append(f"- **EMA20**: {_fmt_money(levels.get('ema20'))}")
    lines.append(f"- **EMA50**: {_fmt_money(levels.get('ema50'))}")
    lines.append(f"- **近期高点**: {_fmt_money(levels.get('recent_high'))}")
    lines.append(f"- **ATR**: {levels.get('atr', '-')}")

    if risk:
        targets = risk.get("targets", {})
        lines.extend(["", "### 风控", ""])
        lines.append(f"- **入场**: {_fmt_money(risk.get('entry'))}")
        lines.append(f"- **止损**: {_fmt_money(risk.get('stop'))}")
        lines.append(f"- **2R / 3R**: {_fmt_money(targets.get('2r'))} / {_fmt_money(targets.get('3r'))}")
        lines.append(f"- **仓位市值**: {_fmt_money(risk.get('position_value'))}，占资金 {_fmt_pct(risk.get('position_pct'))}")
        lines.append(f"- **最大亏损**: {_fmt_money(risk.get('max_loss'))}")

    exit_signals = decision.get("exit_signals") or []
    if exit_signals:
        lines.extend(["", "### 出局信号", ""])
        for signal in exit_signals:
            lines.append(f"- {signal}")

    lines.extend(["", "⚠️ 以上为技术 + 基本面分析参考，不构成投资建议。"])
    return "\n".join(lines)
