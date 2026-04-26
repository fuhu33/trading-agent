"""Trading Agent 统一 CLI 入口

用法:
    uv run trading-agent trend NVDA
    uv run trading-agent fund NVDA
    uv run trading-agent data NVDA
    uv run trading-agent risk --entry 150 --stop 142
    uv run trading-agent sync [--force]
    uv run trading-agent scan [--group mega_cap] [--with-fund]
    uv run trading-agent analyze NVDA
    uv run trading-agent research --group mega_cap --limit 3
    uv run trading-agent watch add NVDA
    uv run trading-agent holding add NVDA --entry 200 --stop 190 --size 10 --initial-logic-score 70
    uv run trading-agent monitor
"""

import sys


def main():
    if len(sys.argv) < 2:
        print("用法: trading-agent <command> [args...]")
        print()
        print("命令:")
        print("  analyze <TICKER>             单标的完整 Agent 分析 (推荐主入口)")
        print("  trend  <TICKER>              趋势分析 + 鱼身定位")
        print("  fund   <TICKER>              基本面叙事分析")
        print("  data   <TICKER>              原始 K 线数据")
        print("  risk   --entry X --stop Y    风控计算")
        print("  sync   [--force]             同步 Bitget 品种列表")
        print("  scan   [TICKERS] [--group G] 批量扫描")
        print("  research [--group G]         扫描后深度研究与候选排名")
        print("  watch   add/list/remove      观察池管理")
        print("  holding add/list/update/remove 持仓状态管理")
        print("  monitor                      观察池与持仓监控")
        print()
        print("示例:")
        print("  uv run trading-agent analyze NVDA")
        print("  uv run trading-agent research --group mega_cap --limit 3")
        print("  uv run trading-agent watch add NVDA --notes ai")
        print("  uv run trading-agent analyze NVDA --json --output reports/NVDA.json")
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
    elif command == "analyze":
        from .analyzer import main as analyze_main
        analyze_main()
    elif command == "research":
        from .research import main as research_main
        research_main()
    elif command == "watch":
        from .state import watch_main
        watch_main()
    elif command == "holding":
        from .state import holding_main
        holding_main()
    elif command == "monitor":
        from .monitor import main as monitor_main
        monitor_main()
    else:
        print(f"未知命令: {command}", file=sys.stderr)
        print(
            "可用命令: trend, fund, data, risk, sync, scan, analyze, "
            "research, watch, holding, monitor",
            file=sys.stderr,
        )
        print("推荐完整分析: uv run trading-agent analyze NVDA", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
