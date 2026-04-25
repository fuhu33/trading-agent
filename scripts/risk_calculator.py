"""
风控计算脚本

基于入场价、止损价和账户参数，计算仓位大小、风险金额和盈亏比目标。

用法:
    uv run python scripts/risk_calculator.py --entry 150 --stop 142
    uv run python scripts/risk_calculator.py --entry 150 --stop 142 --account 50000 --risk-pct 0.01
    uv run python scripts/risk_calculator.py --entry 150 --stop 142 --atr 3.5
"""

import argparse
import json
import sys
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# 核心计算
# ---------------------------------------------------------------------------

def calculate_risk(
    entry: float,
    stop: float,
    account: float = 100000,
    risk_pct: float = 0.02,
    atr: float | None = None,
) -> dict:
    """计算仓位与风控参数

    Args:
        entry: 入场价
        stop: 止损价
        account: 账户总资金 (默认 100000)
        risk_pct: 单笔风险比例 (默认 0.02 = 2%)
        atr: ATR 值 (可选，用于辅助展示)

    Returns:
        包含仓位、风险、盈亏比目标的字典

    Raises:
        ValueError: 参数不合法
    """
    # 参数校验
    if entry <= 0:
        raise ValueError(f"入场价必须 > 0, 当前: {entry}")
    if stop <= 0:
        raise ValueError(f"止损价必须 > 0, 当前: {stop}")
    if entry == stop:
        raise ValueError("入场价与止损价不能相同")
    if account <= 0:
        raise ValueError(f"账户资金必须 > 0, 当前: {account}")
    if not (0 < risk_pct <= 0.1):
        raise ValueError(f"风险比例必须在 (0, 0.1] 之间, 当前: {risk_pct}")

    # 方向判断
    direction = "long" if entry > stop else "short"
    risk_per_share = abs(entry - stop)

    # 仓位计算
    risk_amount = account * risk_pct
    position_size = risk_amount / risk_per_share
    position_value = position_size * entry
    position_pct = position_value / account * 100

    # 最大亏损 (即风险金额)
    max_loss = position_size * risk_per_share

    # 盈亏比目标
    if direction == "long":
        target_2r = entry + 2 * risk_per_share
        target_3r = entry + 3 * risk_per_share
    else:
        target_2r = entry - 2 * risk_per_share
        target_3r = entry - 3 * risk_per_share

    result = {
        "status": "success",
        "direction": direction,
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "risk_per_share": round(risk_per_share, 2),
        "risk_pct_of_entry": round(risk_per_share / entry * 100, 2),
        "account": round(account, 2),
        "risk_pct": risk_pct,
        "risk_amount": round(risk_amount, 2),
        "position_size": round(position_size, 2),
        "position_value": round(position_value, 2),
        "position_pct": round(position_pct, 2),
        "max_loss": round(max_loss, 2),
        "targets": {
            "2r": round(target_2r, 2),
            "3r": round(target_3r, 2),
        },
    }

    if atr is not None:
        result["atr"] = round(atr, 2)
        result["stop_atr_multiple"] = round(risk_per_share / atr, 2) if atr > 0 else None

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="风控计算: 仓位、止损、盈亏比"
    )
    parser.add_argument("--entry", type=float, required=True,
                        help="入场价")
    parser.add_argument("--stop", type=float, required=True,
                        help="止损价")
    parser.add_argument("--account", type=float, default=100000,
                        help="账户总资金 (默认: 100000)")
    parser.add_argument("--risk-pct", type=float, default=0.02,
                        help="单笔风险比例 (默认: 0.02 = 2%%)")
    parser.add_argument("--atr", type=float, default=None,
                        help="ATR 值 (可选)")
    args = parser.parse_args()

    try:
        result = calculate_risk(
            entry=args.entry,
            stop=args.stop,
            account=args.account,
            risk_pct=args.risk_pct,
            atr=args.atr,
        )
    except ValueError as e:
        print(json.dumps({"status": "error", "message": str(e)},
                         ensure_ascii=False))
        sys.exit(1)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
