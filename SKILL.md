---
name: swing-analysis
description: "美股波段分析工作流 (基本面 + 技术面双驱动)。先用基本面叙事筛选业绩驱动标的, 再用技术面 + 鱼身定位找最佳介入时机, 目标是 1-2 周波段持仓吃鱼身行情。触发词: swing, 波段分析, 趋势分析, swing trade"
---

## 使用方式

### 单只完整分析 (基本面 + 技术面双驱动)
```
swing NVDA          — 完整流程: Stage 0 (基本面) + Stage 1+2 (技术面+鱼身) + 整合推理
波段分析 AAPL
```

### 子命令 (仅运行脚本，不触发推理)
```
swing fund NVDA     — 仅基本面分析 (业绩/行业/评级)
swing trend NVDA    — 仅技术面 + 鱼身定位 (展示指标)
swing data NVDA     — 仅获取原始行情数据
swing risk --entry 150 --stop 142  — 仅风控计算
swing sync          — 同步 Bitget 品种列表
swing report NVDA              — 生成 HTML K线图报告
swing report MSFT,META,AAPL    — 批量生成 + 索引页
swing report NVDA --serve      — 本地服务器预览
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

---

## 核心流程: 双驱动决策模型

```
Stage 0: 基本面叙事审查 (fundamentals.py)
  └── 业绩超预期? 行业景气? 机构看多? 财报窗口?
  └── 输出 narrative.score (0-10) + thesis (strong/moderate/weak) + earnings_catalyst
        ↓
[决策门 1] thesis=weak 且 score<4 → 直接拦截, 不做
        ↓
Stage 1: 技术 Gate + 鱼身定位 (trend.py)
  └── 趋势成立? (Gate)
  └── 鱼身位置? (鱼头/鱼身/鱼尾)
        ↓
[决策门 2] gate.pass=false → 加入 Watchlist
        ↓
Stage 2: 整合推理 (swing_analyst.md, 5 步)
  └── Step 0: 基本面叙事
  └── Step 1: 趋势 + 鱼身
  └── Step 2: 延续动力
  └── Step 3: 共振分析 (核心)
  └── Step 4: 风控建议
        ↓
Stage 3: 风控计算 + 输出报告 (output_schema.md)
```

**核心理念**: 基本面提供"故事强度"，技术面提供"介入时机"，鱼身定位回答"是不是吃鱼身的位置"。三层共振才是核心持仓信号。

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
   仅对 Gate 通过的标的进行 Stage 2 深度推理。
7. **`swing report <tickers> [--serve]`**: 生成 HTML K线图交互报告
   ```bash
   uv run trading-agent report <TICKERS> [--with-fund] [--serve] [--no-open]
   ```
8. **`swing <ticker>`** (无子命令): 执行完整双驱动流程

### 完整双驱动流程

**Step 1: 基本面叙事 (Stage 0)**

```bash
uv run trading-agent fund <TICKER>
```

读取 `narrative.score`、`narrative.thesis` 与 `narrative.earnings_catalyst`:

- **拦截分支 A**: `thesis == "weak"` 且 `score < 4`
  → 输出 `output_schema.md` 中的 "分支 A: 基本面拦截" 模板
  → **不进行技术面分析，流程结束**
- **通过**: 进入 Step 2

**Step 2: 技术面 + 鱼身 (Stage 1)**

```bash
uv run trading-agent trend <TICKER>
```

新输出包含 `fish_body` 字段 (stage / trend_age_days / cumulative_pct / deviation_pct / ideal_entry)。

**Step 3: Gate 判断**

读取 `gate.pass`:

- **拦截分支 B**: `gate.pass == false`
  → 输出 "分支 B: Gate FAIL" 模板 (注明基本面状态)
  → **不进入深度推理**
- **通过**: 进入 Step 4

**Step 4: 整合推理 (Stage 2, 核心)**

按 `prompts/swing_analyst.md` 的 5 步推理:

1. **基本面叙事审查**: 引用 `narrative.drivers/concerns`
2. **趋势 + 鱼身**: 引用 `trend.*` 和 `fish_body.*`
3. **延续动力**: 引用 `continuation.*`
4. **共振分析** (核心): 三维交叉 (基本面 × 鱼身 × 动力) → 决策矩阵
5. **风控建议**: ATR-based 止损 + 分析师目标价

**Step 5: 风控计算 (如建议入场)**

```bash
uv run trading-agent risk --entry <ENTRY> --stop <STOP> --atr <ATR>
```

**Step 6: 按 `output_schema.md` 完整模板输出**

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
├── risk.py             # 风控计算
└── scanner.py          # 批量扫描

prompts/
├── swing_analyst.md    # 5 步推理框架
└── output_schema.md    # 报告模板

config/
├── bitget_symbols.json      # 品种缓存 (24h TTL)
└── fundamentals_cache.json  # 基本面缓存 (6h TTL)

tests/
├── test_risk_calculator.py  # 风控计算测试
├── test_trend_analysis.py   # 趋势分析测试
├── test_fundamentals.py     # 基本面评分测试
└── test_scanner.py          # 扫描模块测试

.env                          # FINNHUB_API_KEY (gitignored)
.env.example                  # 模板
```

所有命令通过 `uv run trading-agent <command>` 执行。
