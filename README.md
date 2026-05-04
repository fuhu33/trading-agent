# Trading Agent — 美股波段分析系统

> **目标**: 找到由业绩驱动 + 行业景气 + 技术健康的标的，吃 1-2 周的鱼身行情。

通过 **基本面叙事 + 技术面鱼身定位 + 逻辑强度评分 + 决策引擎** 的共振模型，输出可执行的波段持仓决策（含仓位倍数 + 风控）。

> **策略边界**: 当前框架默认只评估做多波段；空头趋势用于回避/观察，不主动输出做空建议。

---

## 核心理念

```
入场决定 = 基本面叙事 + 技术 Gate          (做不做)
仓位大小 = 鱼身阶段 + 动力 + ideal_entry   (做多大)
出局信号 = 趋势破位 / 触及止损 / 触及目标   (什么时候出)
```

**关键原则**: "贵位置"不是不做的理由，而是降低仓位的理由。只有趋势破位（Gate FAIL）才是真正的出局信号。

---

## 双驱动决策流程

```
┌─────────────────────────────────────────────────────────┐
│  Stage 0: 基本面叙事审查 (fundamentals.py)               │
│  ├─ 业绩超预期? (yfinance.earnings_history)             │
│  ├─ 行业景气? (sector ETF 5d/20d 趋势)                  │
│  ├─ 机构看多? (analysts rating + target_mean)           │
│  └─ 财报窗口? → earnings_catalyst                       │
│  → narrative.score + thesis + earnings_catalyst          │
└─────────────────────────────────────────────────────────┘
              ↓
       [决策门 1] thesis=weak 且 score<4 → 拦截不做
              ↓
┌─────────────────────────────────────────────────────────┐
│  Stage 1: 技术 Gate + 鱼身定位 (trend.py)              │
│  ├─ 趋势成立? (ADX>=20 + EMA 排列 → Gate)              │
│  └─ 鱼身位置? (启动时长 + 累计涨幅 + 偏离度)             │
│  → fish_body.stage (early/mid/late) + ideal_entry       │
└─────────────────────────────────────────────────────────┘
              ↓
       [决策门 2] gate.pass=false → Watchlist
              ↓
┌─────────────────────────────────────────────────────────┐
│  Stage 2: 逻辑强度评分 (logic.py)                       │
│  └─ logic.score + logic.trend + drivers/weaknesses       │
└─────────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────────┐
│  Stage 3: 决策 + 风控 + 报告 (decision/risk/reporter)   │
│  ├─ 介入/小仓/观察/拒绝/减仓                              │
│  ├─ ATR 止损 + 仓位风险                                  │
│  └─ JSON 或 Markdown 输出                                │
└─────────────────────────────────────────────────────────┘
```

---

## 快速开始

### 环境准备

```bash
# 1. 安装 uv (Python 包管理器)
curl -LsSf https://astral.sh/uv/install.sh | sh   # macOS/Linux
# Windows: powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. 同步依赖
uv sync

# 3. (可选) 配置 .env
cp .env.example .env
```

### 单只完整分析

```bash
# 通过 SKILL.md 触发 Antigravity Agent (推荐)
swing NVDA

# 或直接跑完整 CLI
uv run trading-agent analyze NVDA
uv run trading-agent analyze NVDA --json

# 分步调试命令
uv run trading-agent fund NVDA      # Stage 0
uv run trading-agent trend NVDA     # Stage 1
uv run trading-agent risk --entry 209 --stop 195 --atr 4.89

# 美股参考池情绪
uv run trading-agent sentiment --tickers AAPL,MSFT,NVDA,TSLA --top 3
uv run trading-agent sentiment --tickers config/us_equity_universe.json --top 200 --compare 100,500 --validate
```

### 批量扫描

```bash
# 仅技术面 (快, 约 1-2 分钟)
uv run trading-agent scan --group mega_cap --delay 1.5

# 技术面 + 基本面 (慢但更准, 约 3-5 分钟)
uv run trading-agent scan --group mega_cap --delay 1.5 --with-fund

# 全量 RWA 品种 (77 只, 约 10 分钟)
uv run trading-agent scan --with-fund --delay 1.5
```

### 深度研究与监控

```bash
# 扫描后只对 Gate 通过标的做完整 analyze 并排序
uv run trading-agent research --group mega_cap --limit 3
uv run trading-agent research AAPL,MSFT,NVDA --json

# 观察池与持仓监控
uv run trading-agent watch add NVDA --notes "AI leader"
uv run trading-agent holding add NVDA --entry 200 --stop 190 --size 10 --initial-logic-score 72
uv run trading-agent monitor
```

---

## 命令体系

### CLI 命令

| 命令 | 行为 |
|------|------|
| `uv run trading-agent analyze NVDA` | 单标的完整 Agent 分析，推荐主入口 |
| `uv run trading-agent analyze NVDA --json` | 输出完整结构化 JSON |
| `uv run trading-agent fund NVDA` | 仅基本面叙事 |
| `uv run trading-agent trend NVDA` | 仅技术面 + 鱼身定位 |
| `uv run trading-agent data NVDA` | 仅原始 K 线 |
| `uv run trading-agent risk --entry 150 --stop 142` | 仅风控计算 |
| `uv run trading-agent scan --group mega_cap` | 批量趋势扫描 |
| `uv run trading-agent scan --with-fund` | 扫描 + 基本面摘要 |
| `uv run trading-agent research --group mega_cap --limit 3` | 扫描后深度研究与候选排名 |
| `uv run trading-agent sentiment --tickers AAPL,MSFT,NVDA --top 3` | yfinance 美股参考池情绪指标 |
| `uv run trading-agent sentiment --tickers config/us_equity_universe.json --top 200 --compare 100,500 --validate` | Top200 情绪 + 宽窄对比 + 轻量历史验证 |
| `uv run trading-agent watch add NVDA` | 添加观察标的 |
| `uv run trading-agent holding add NVDA --entry 200 --stop 190 --size 10 --initial-logic-score 72` | 添加持仓状态 |
| `uv run trading-agent monitor` | 监控观察池与持仓 |
| `uv run trading-agent sync` | 同步 Bitget 品种列表 |

### Skill 触发

| 命令 | 行为 |
|------|------|
| `swing NVDA` | 调用 `analyze`，再由 Agent 解释结构化结果 |
| `swing fund NVDA` | 调用 `fund` |
| `swing trend NVDA` | 调用 `trend` |
| `swing scan --group mega_cap` | 调用 `scan` |
| `swing research --group mega_cap` | 调用 `research` |
| `swing monitor` | 调用 `monitor` |

> `report`、`job`、自动通知、自动下单当前是后续规划能力，不属于本版本已实现 CLI。

---

## 仓位决策矩阵

基础风险 X = 账户资金 × `--risk-pct` (默认 2%)

| 鱼身阶段 | ideal_entry | 动力 | 仓位倍数 | 单笔风险 | 说明 |
|---------|------------|------|---------|---------|------|
| 鱼头 (early) | true | strong | **1.5×** | 3.0% | 跑道最长, 风险报酬比最佳 |
| 鱼头 (early) | false | strong | 1.0× | 2.0% | 趋势刚起但位置略远 |
| 鱼身 (mid) | true | strong | **1.2×** | 2.4% | 主力波段区, 标准重仓 |
| 鱼身 (mid) | true | moderate | 1.0× | 2.0% | 标准仓位 |
| 鱼身 (mid) | false | strong | 0.6× | 1.2% | 位置贵, 减仓试单 |
| 鱼身 (mid) | false | moderate | 0.4× | 0.8% | 贵 + 动力一般 |
| 鱼尾 (late) | any | strong | 0.4× | 0.8% | 尾段动能在, 轻仓搏 |
| 鱼尾 (late) | any | weakening | **0×** | — | 衰竭信号, 拒绝入场 |

**调整因子** (在仓位倍数基础上修正):
- strong 叙事 + `earnings_catalyst=true`: 财报窗口不打折, 但不自动升档
- moderate 叙事: 矩阵基础倍数 ×0.5, 下限 0.3×
- 中性叙事 + 财报窗口: ×0.7
- 弱叙事 + 财报窗口: ×0.3 或回避
- RSI 超买 + 鱼尾: ×0.7
- 已超分析师目标价: ×0.7

---

## 项目结构

```
trading-agent/
├── README.md                    # 本文件
├── SKILL.md                     # Antigravity Skill 入口 (触发规则 + 工作流)
├── TODO.md                      # 历史开发追踪
├── AGENT_FRAMEWORK_TODO.md      # Agent 框架优化追踪
├── pyproject.toml               # 依赖管理 (uv + hatchling)
├── .env.example / .env          # 本地环境配置 (.env gitignored)
│
├── src/trading_agent/           # 核心包
│   ├── __init__.py              # 包入口
│   ├── cli.py                   # 统一 CLI 入口
│   ├── exceptions.py            # 异常层级
│   ├── utils.py                 # 共用工具函数
│   ├── symbols.py               # Bitget RWA 品种同步 (77 只)
│   ├── data.py                  # K 线获取 (Bitget API)
│   ├── yfinance_data.py         # yfinance OHLCV 标准化与 ticker master 读取
│   ├── sentiment.py             # 美股参考池情绪指标
│   ├── fundamentals.py          # Stage 0: 基本面叙事 (yfinance)
│   ├── trend.py                 # Stage 1: 技术面 + 鱼身定位
│   ├── logic.py                 # 逻辑强度评分与变化判断
│   ├── history.py               # 本地逻辑强度历史
│   ├── decision.py              # 决策引擎与仓位倍数
│   ├── analyzer.py              # 单标的完整编排入口
│   ├── research.py              # 扫描后深度研究与候选排名
│   ├── state.py                 # 观察池与持仓状态
│   ├── monitor.py               # 观察池/持仓监控
│   ├── reporter.py              # Markdown 报告渲染
│   ├── risk.py                  # 风控计算 (ATR-based)
│   └── scanner.py               # 批量扫描 (支持 --with-fund)
│
├── prompts/
│   ├── swing_analyst.md         # 5 步推理框架 (含决策矩阵 + 7 个 few-shot)
│   └── output_schema.md         # 报告输出模板
│
├── tests/
│   ├── test_analyzer.py
│   ├── test_decision.py
│   ├── test_fundamentals.py
│   ├── test_history.py
│   ├── test_logic.py
│   ├── test_monitor.py
│   ├── test_research.py
│   ├── test_sentiment.py
│   ├── test_sentiment_cli.py
│   ├── test_yfinance_data.py
│   ├── test_risk_calculator.py
│   ├── test_state.py
│   ├── test_trend_analysis.py
│   └── test_scanner.py
│
└── config/
│   ├── bitget_symbols.json      # Bitget 品种缓存 (24h TTL)
│   ├── fundamentals_cache.json  # 基本面缓存 (6h TTL, gitignored)
│   └── logic_history.json       # 逻辑强度历史 (gitignored)
│
└── reports/                     # 生成报告输出目录 (gitignored)
```

---

## 数据源

| 类型 | 数据源 | 用途 | 限制 |
|------|--------|------|------|
| **K 线** | yfinance OHLCV | 交易池标的价格 + 量能 + 技术指标 | Bitget 只做交易池，行情不取 Bitget 合约 K 线 |
| **品种列表** | Bitget API (`/api/v2/mix/market/contracts`) | 77 只 RWA: 57 stock + 12 ETF + 8 commodity | 公开接口, 无需 Key，仅用于交易池 |
| **市场情绪** | yfinance OHLCV + 外部 ticker master | 美股前排参考池攻击/回头、广度、新高新低、MA20 修复 | yfinance 偶尔超时，ticker master 需维护 |
| **基本面** | yfinance | 业绩 / sector / 评级 / 目标价 / 财报日历 | 偏爬虫, 偶尔超时 |

> **数据约束**: 技术分析仅限 Bitget 已上线的 RWA 合约品种，但行情/K 线统一使用 yfinance。情绪指标使用 yfinance 美股参考池，Bitget 股票池只作为交易池。
> 大宗商品 (XAU/XAG/COPPER 等) 不做基本面分析 (无财报概念)。

`sentiment` 命令支持 yfinance 分块、重试和本地价格缓存：

```bash
uv run trading-agent sentiment \
  --tickers config/us_equity_universe.json \
  --top 200 \
  --compare 100,500 \
  --chunk-size 80 \
  --retries 2 \
  --validate \
  --benchmarks SPY,QQQ \
  --forward 1,3,5
```

---

## 报告示例

完整报告包含以下板块:

```
## NVDA 波段分析

**当前结论**: Enter

### 核心状态

- 价格、趋势 Gate、逻辑强度、鱼身阶段、趋势持续性

### 决策

- 动作、仓位倍数、最终单笔风险、理由、调整因子

### 逻辑强度

- 驱动因素、隐忧、逻辑变化

### 风控

- 入场、止损、2R/3R、仓位市值、最大亏损
```

---

## 当前 MVP 边界

- 已完成单标的完整分析闭环：`analyze`。
- 已完成批量趋势扫描：`scan`。
- 已完成扫描后深度研究与候选排名：`research`。
- 已完成观察池、持仓状态与监控：`watch`、`holding`、`monitor`。
- 已完成基本面、技术面、逻辑强度、决策和风控的结构化输出。
- 尚未实现 `report`、`job`、自动通知、自动下单。
- 后续 Hermes Agent 定时执行应优先基于 `research --json`、`monitor --json` 和报告落盘能力扩展。

---

## 开发追踪

历史任务追踪见 [`TODO.md`](TODO.md)，Agent 框架优化见 [`AGENT_FRAMEWORK_TODO.md`](AGENT_FRAMEWORK_TODO.md):

- **Phase 1**: 基础骨架 (Bitget 同步 + 趋势分析 + Skill) ✅
- **Phase 2**: 推理深化 (Prompt + 风控 + 输出格式) ✅
- **Phase 3**: 扩展能力 (批量扫描 + 分组) ✅
- **Phase 4**: 双驱动重构 (基本面 + 鱼身定位 + 仓位矩阵) ✅
- **Agent MVP**: `analyze + logic + history + decision + reporter` ✅
- **Research/Monitor MVP**: `research + watch + holding + monitor` ✅
- **下一阶段**: Hermes 定时任务、报告归档、通知通道

---

## 风险声明

⚠️ 本系统输出为技术 + 基本面分析参考，**不构成投资建议**。
- 实盘交易前请自行核对数据
- 美股波段持仓存在隔夜跳空风险
- 财报窗口前后波动剧烈, 请遵守仓位管理规则
- 大宗商品分析仅有技术面, 缺基本面共振
