"""Trading Agent 统一 CLI 入口

用法:
    uv run trading-agent trend NVDA
    uv run trading-agent fund NVDA
    uv run trading-agent data NVDA
    uv run trading-agent risk --entry 150 --stop 142
    uv run trading-agent sync [--force]
    uv run trading-agent scan [--group mega_cap] [--with-fund]
"""

import sys


def main():
    if len(sys.argv) < 2:
        print("用法: trading-agent <command> [args...]")
        print()
        print("命令:")
        print("  trend  <TICKER>              趋势分析 + 鱼身定位")
        print("  fund   <TICKER>              基本面叙事分析")
        print("  data   <TICKER>              原始 K 线数据")
        print("  risk   --entry X --stop Y    风控计算")
        print("  sync   [--force]             同步 Bitget 品种列表")
        print("  scan   [TICKERS] [--group G] 批量扫描")
        sys.exit(1)

    command = sys.argv[1]
    # 移除 command 参数, 让子模块的 argparse 解析剩余参数
    sys.argv = [f"trading-agent {command}"] + sys.argv[2:]

    if command == "trend":
        from .trend import main as trend_main
        trend_main()
    elif command == "fund":
        from .fundamentals import main as fund_main
        fund_main()
    elif command == "data":
        from .data import main as data_main
        data_main()
    elif command == "risk":
        from .risk import main as risk_main
        risk_main()
    elif command == "sync":
        from .symbols import main as sync_main
        sync_main()
    elif command == "scan":
        from .scanner import main as scan_main
        scan_main()
    else:
        print(f"未知命令: {command}", file=sys.stderr)
        print("可用命令: trend, fund, data, risk, sync, scan", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
