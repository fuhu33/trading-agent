# Trading Agent — 美股波段分析系统

> **目标**: 找到由业绩驱动 + 行业景气 + 技术健康的标的，吃 1-2 周的鱼身行情。

通过 **基本面叙事 + 技术面鱼身定位 + AI Agent 推理** 三层共振模型，输出可执行的波段持仓决策（含仓位倍数 + 风控）。

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
│  └─ 财报窗口? (next_earnings.in_window)                 │
│  → narrative.score (0-10) + thesis (strong/moderate/weak)│
└─────────────────────────────────────────────────────────┘
              ↓
       [决策门 1] thesis=weak 且 score<4 → 拦截不做
              ↓
┌─────────────────────────────────────────────────────────┐
│  Stage 1: 技术 Gate + 鱼身定位 (trend_analysis.py)       │
│  ├─ 趋势成立? (ADX>=20 + EMA 排列 → Gate)              │
│  └─ 鱼身位置? (启动时长 + 累计涨幅 + 偏离度)             │
│  → fish_body.stage (early/mid/late) + ideal_entry       │
└─────────────────────────────────────────────────────────┘
              ↓
       [决策门 2] gate.pass=false → Watchlist
              ↓
┌─────────────────────────────────────────────────────────┐
│  Stage 2: 整合推理 (swing_analyst.md, 5 步)              │
│  └─ 共振分析 → 仓位倍数 (1.5×/1.2×/1.0×/0.6×/0.4×/0×)  │
└─────────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────────┐
│  Stage 3: 风控 + 报告 (risk_calculator.py)               │
│  ├─ ATR 止损 + 分阶段目标价                              │
│  └─ 按 output_schema.md 模板输出                         │
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

# 3. (可选) 配置 Finnhub API Key 提高财报日历可靠性
cp .env.example .env
# 编辑 .env, 填入 FINNHUB_API_KEY (https://finnhub.io 免费注册)
```

### 单只完整分析

```bash
# 通过 SKILL.md 触发 Antigravity Agent (推荐)
swing NVDA

# 或直接跑脚本三连击
uv run python scripts/fundamentals.py NVDA      # Stage 0
uv run python scripts/trend_analysis.py NVDA    # Stage 1
uv run python scripts/risk_calculator.py --entry 209 --stop 195 --atr 4.89
```

### 批量扫描

```bash
# 仅技术面 (快, 约 1-2 分钟)
uv run python scripts/batch_scan.py --group mega_cap --delay 1.5

# 技术面 + 基本面 (慢但更准, 约 3-5 分钟)
uv run python scripts/batch_scan.py --group mega_cap --delay 1.5 --with-fund

# 全量 RWA 品种 (68 只, 约 10 分钟)
uv run python scripts/batch_scan.py --with-fund --delay 1.5
```

---

## 命令体系 (在 Antigravity 中触发 SKILL.md)

| 命令 | 行为 | 调用 LLM |
|------|------|:---:|
| `swing NVDA` | 完整双驱动分析 (Stage 0 + 1 + 推理 + 风控) | ✅ |
| `swing fund NVDA` | 仅基本面叙事 | ❌ |
| `swing trend NVDA` | 仅技术面 + 鱼身定位 | ❌ |
| `swing data NVDA` | 仅原始 K 线 | ❌ |
| `swing risk --entry 150 --stop 142` | 仅风控计算 | ❌ |
| `swing scan` | 全量 RWA 扫描 (仅技术) | 部分 |
| `swing scan --with-fund` | 扫描 + 基本面 (推荐三层共振筛选) | 部分 |
| `swing scan --group mega_cap` | 大盘科技股扫描 | 部分 |
| `swing sync` | 同步 Bitget 品种列表 | ❌ |

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
- 财报 14 天内: ×0.5
- RSI 超买 + 鱼尾: ×0.7
- 已超分析师目标价: ×0.7

---

## 项目结构

```
trading-agent/
├── README.md                    # 本文件
├── SKILL.md                     # Antigravity Skill 入口 (触发规则 + 工作流)
├── TODO.md                      # 详细开发追踪 (Phase 1-4)
├── pyproject.toml               # 依赖管理 (uv)
├── .env.example / .env          # Finnhub API Key (.env gitignored)
│
├── scripts/                     # 6 个核心脚本
│   ├── sync_bitget_symbols.py   # Bitget RWA 品种同步 (68 只)
│   ├── fetch_data.py            # K 线获取 (Bitget API)
│   ├── fundamentals.py          # Stage 0: 基本面叙事 (yfinance + Finnhub)
│   ├── trend_analysis.py        # Stage 1: 技术面 + 鱼身定位
│   ├── risk_calculator.py       # 风控计算 (ATR-based)
│   └── batch_scan.py            # 批量扫描 (支持 --with-fund)
│
├── prompts/
│   ├── swing_analyst.md         # 5 步推理框架 (含决策矩阵 + 7 个 few-shot)
│   └── output_schema.md         # 报告输出模板
│
└── config/
    ├── bitget_symbols.json      # Bitget 品种缓存 (24h TTL)
    └── fundamentals_cache.json  # 基本面缓存 (6h TTL, gitignored)
```

---

## 数据源

| 类型 | 数据源 | 用途 | 限制 |
|------|--------|------|------|
| **K 线** | Bitget API (`/api/v2/mix/market/history-candles`) | 价格 + 量能 + 技术指标 | 最多 90 天日 K, 仅 RWA 合约 |
| **品种列表** | Bitget API (`/api/v2/mix/market/contracts`) | 68 只美股+ETF+大宗商品 | 公开接口, 无需 Key |
| **基本面** | yfinance | 业绩 / sector / 评级 / 目标价 | 偏爬虫, 偶尔超时 |
| **财报日历** | Finnhub | 下次财报日 (yfinance 兜底) | 60 次/分钟免费额度 |

> **数据约束**: 技术分析仅限 Bitget 已上线的 68 个 RWA 合约品种 (50 美股 + 12 ETF + 6 大宗商品)。
> 大宗商品 (XAU/XAG/COPPER 等) 不做基本面分析 (无财报概念)。

---

## 报告示例

完整报告包含 5 个板块:

```
## NVDA 波段分析报告 | 2026-04-25
**叙事**: 故事强 (7/10) | **趋势**: 多头 | **鱼身**: 鱼身 | **Gate**: ✅ PASS

### 📖 基本面叙事
- 业绩 超预期 +5.32%
- 行业 SMH 月线 +33%
- 评级 Strong Buy (1.29 / 56 位分析师)
- 目标价 +29% 上涨空间

### 📊 趋势 + 鱼身定位
- 多头 strong, ADX 33.78
- 启动 11 天前, 累计 +11.17%, 偏离 +7.73%

### ⚡ 延续动力: 动力强劲
- MACD 加速, ADX 上升, 量比 1.83x

### 🎯 共振分析与仓位决策
- 入场: ✅ 做
- 仓位倍数: 0.6× → 单笔风险 1.2%

### 🛡️ 风控建议
- 入场 $209 / 止损 $200 / 2R 目标 $227 / 中线目标 $268
```

---

## 开发追踪

详细任务追踪见 [`TODO.md`](TODO.md):

- **Phase 1**: 基础骨架 (Bitget 同步 + 趋势分析 + Skill) ✅
- **Phase 2**: 推理深化 (Prompt + 风控 + 输出格式) ✅
- **Phase 3**: 扩展能力 (批量扫描 + 分组) ✅
- **Phase 4**: 双驱动重构 (基本面 + 鱼身定位 + 仓位矩阵) ✅
- **Phase 5** (待定): VPS 部署 + 历史对比 + 期权数据

---

## 风险声明

⚠️ 本系统输出为技术 + 基本面分析参考，**不构成投资建议**。
- 实盘交易前请自行核对数据
- 美股波段持仓存在隔夜跳空风险
- 财报窗口前后波动剧烈, 请遵守仓位管理规则
- 大宗商品分析仅有技术面, 缺基本面共振
