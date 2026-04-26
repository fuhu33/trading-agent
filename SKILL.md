---
name: swing-analysis
description: "美股波段分析工作流 (基本面 + 技术面双驱动 + 逻辑强度 + 决策引擎)。触发词: swing, 波段分析, 趋势分析, swing trade"
---

## 使用方式

### 单只完整分析 (基本面 + 技术面双驱动)
```
swing NVDA          — 调用 analyze 完整分析，再由 Agent 解释结构化结果
波段分析 AAPL
```

### 子命令
```
swing fund NVDA     — 仅基本面分析 (业绩/行业/评级)
swing trend NVDA    — 仅技术面 + 鱼身定位 (展示指标)
swing data NVDA     — 仅获取原始行情数据
swing risk --entry 150 --stop 142  — 仅风控计算
swing sync          — 同步 Bitget 品种列表
swing research --group mega_cap --limit 3  — 扫描后深度研究与候选排名
swing watch add NVDA --notes "AI leader"   — 添加观察标的
swing holding add NVDA --entry 200 --stop 190 --size 10 --initial-logic-score 72
swing monitor       — 监控观察池与持仓
```

### 批量扫描
```
swing scan                  — 扫描全部 Bitget RWA (68, 仅技术面)
swing scan --with-fund      — 扫描 + 基本面 (慢但更准)
swing scan --group stock    — 仅美股个股 (50)
swing scan --group mega_cap — 大盘科技股 (7)
swing scan AAPL,MSFT,NVDA   — 指定品种
```

> **数据约束**: 技术面分析仅限 Bitget 已上线的 RWA 合约品种 (68 个)。基本面来自 yfinance + Finnhub。
> **策略边界**: 当前框架默认只评估做多波段；`bearish` 趋势用于回避/观察，不主动输出做空建议。
> **当前边界**: `report`、`job`、自动通知、自动下单仍是后续规划能力，不属于当前已实现 CLI。

---

## 核心流程: 代码判断，Agent 解释

```
Stage 0: 基本面叙事审查 (fundamentals.py)
  └── 业绩超预期? 行业景气? 机构看多? 财报窗口?
  └── 输出 narrative.score + thesis + earnings_catalyst
        ↓
Stage 1: 技术 Gate + 鱼身定位 (trend.py)
  └── 趋势成立? 鱼身位置? 延续动力?
        ↓
Stage 2: 逻辑强度评分 (logic.py)
  └── logic.score / logic.grade / logic.trend / drivers / weaknesses
        ↓
Stage 3: 决策 + 风控 + 报告 (decision.py / risk.py / reporter.py)
  └── enter / small_enter / watch / reject / reduce
```

**核心理念**: Python 代码负责稳定地产生结构化判断；Agent 负责调度命令、读取 JSON、解释原因、追问用户风险偏好并输出自然语言报告。

---

## 执行步骤

### 子命令分发

收到用户输入后，先解析子命令:

1. **`swing fund <ticker>`**: 运行 Stage 0, 仅展示基本面叙事报告
   ```bash
   uv run trading-agent fund <TICKER>
   ```
2. **`swing trend <ticker>`**: 运行 Stage 1, 展示技术指标 + 鱼身定位
   ```bash
   uv run trading-agent trend <TICKER>
   ```
3. **`swing data <ticker>`**: 仅获取原始 OHLCV
   ```bash
   uv run trading-agent data <TICKER>
   ```
4. **`swing risk --entry X --stop Y`**: 仅风控
   ```bash
   uv run trading-agent risk --entry <ENTRY> --stop <STOP> --atr <ATR>
   ```
5. **`swing sync [--force]`**: 同步品种
   ```bash
   uv run trading-agent sync [--force]
   ```
6. **`swing scan [tickers] [--group G] [--with-fund]`**: 批量扫描
   ```bash
   uv run trading-agent scan [TICKERS] [--group GROUP] [--delay 1.5] [--with-fund]
   ```
7. **`swing research [tickers] [--group G] [--limit N]`**: 扫描后深度研究与排名
   ```bash
   uv run trading-agent research [TICKERS] [--group GROUP] [--limit N] --json
   ```
8. **`swing watch ...` / `swing holding ...` / `swing monitor`**: 状态管理与监控
   ```bash
   uv run trading-agent watch add <TICKER> [--notes TEXT]
   uv run trading-agent holding add <TICKER> --entry <ENTRY> --stop <STOP> --size <SIZE> --initial-logic-score <SCORE>
   uv run trading-agent monitor --json
   ```
9. **`swing analyze <ticker>`** 或 **`swing <ticker>`**: 单标的完整分析
   ```bash
   uv run trading-agent analyze <TICKER> --json
   ```

### 完整双驱动流程

默认 `swing <ticker>` 应调用:

```bash
uv run trading-agent analyze <TICKER> --json
```

Agent 读取 JSON 后重点解释:

- `decision_report.action` 和 `action_label`
- `decision_report.position_multiplier`
- `decision_report.reasons`
- `decision_report.adjustments`
- `logic_report.logic.score`
- `logic_report.logic.trend`
- `trend_report.gate`
- `trend_report.fish_body`
- `risk_report`

Agent 不应重新计算仓位矩阵或临场改写核心业务规则。

---

## 项目结构

```
src/trading_agent/
├── __init__.py         # 包入口
├── cli.py              # 统一 CLI 入口
├── exceptions.py       # 异常层级
├── utils.py            # 共用工具函数
├── symbols.py          # 品种同步 (Bitget API)
├── data.py             # K 线获取 (Bitget API)
├── trend.py            # 技术面 + 鱼身定位
├── fundamentals.py     # 基本面叙事 (yfinance + Finnhub)
├── logic.py            # 逻辑强度评分与变化判断
├── history.py          # 本地逻辑强度历史
├── decision.py         # 决策引擎与仓位倍数
├── analyzer.py         # 单标的完整编排入口
├── research.py         # 扫描后深度研究与候选排名
├── state.py            # 观察池与持仓状态
├── monitor.py          # 观察池与持仓监控
├── reporter.py         # Markdown 报告渲染
├── risk.py             # 风控计算
└── scanner.py          # 批量扫描

prompts/
├── swing_analyst.md    # 5 步推理框架
└── output_schema.md    # 报告模板

config/
├── bitget_symbols.json      # 品种缓存 (24h TTL)
├── fundamentals_cache.json  # 基本面缓存 (6h TTL)
└── logic_history.json       # 逻辑强度历史

tests/
├── test_analyzer.py         # 编排层测试
├── test_decision.py         # 决策引擎测试
├── test_history.py          # 逻辑历史测试
├── test_logic.py            # 逻辑评分测试
├── test_research.py         # 深度研究测试
├── test_state.py            # 状态管理测试
├── test_monitor.py          # 监控测试
├── test_risk_calculator.py  # 风控计算测试
├── test_trend_analysis.py   # 趋势分析测试
├── test_fundamentals.py     # 基本面评分测试
└── test_scanner.py          # 扫描模块测试

.env                          # FINNHUB_API_KEY (gitignored)
.env.example                  # 模板
```

所有命令通过 `uv run trading-agent <command>` 执行。
