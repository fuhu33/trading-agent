# 美股波段分析 Skill - 开发 TODO

> 项目目标: 构建 Antigravity Skill，通过 `/swing` 命令触发美股波段分析工作流。
> 架构模式: 双驱动 (基本面叙事 + 技术面鱼身定位 + Agent 推理)
> 持仓周期: **1-2 周波段，吃鱼身行情**
> Skill 路径: `C:\Users\Administrator\.gemini\antigravity\skills\swing-analysis\`

---

## 命令体系

Skill 支持子命令，用户可按需选择调用粒度：

| 命令 | 行为 | 调用 LLM 推理 |
|------|------|:---:|
| `swing AAPL` | 完整流程 (数据+指标+Gate+推理) | 是 (仅通过Gate时) |
| `swing trend AAPL` | 只跑趋势分析脚本，展示指标数据 | 否 |
| `swing data AAPL` | 只获取原始行情数据 | 否 |
| `swing risk --entry 150 --stop 142` | 只跑风控计算 | 否 |
| `swing sync` | 同步 Bitget 最新美股合约品种列表 | 否 |
| `swing scan` | 扫描全部 Bitget RWA 品种 (Phase 3) | 部分 |
| `swing scan --group stock` | 仅扫描美股个股 (Phase 3) | 部分 |

脚本本身也可脱离 Skill 独立运行：`python trend_analysis.py AAPL`

> **数据约束**: 所有分析仅限 Bitget 已上线的美股合约品种 (RWA)。
> 输入不在 Bitget 品种列表中的 ticker 时，会提示该品种不可交易。

---

## Phase 1: 基础骨架 (最小可用闭环)

### 1.1 环境准备

- [x] 确认 uv 已安装 (v0.10.4)
- [x] `uv python pin 3.11` 固定 Python 版本 (避免 3.14 无预编译 wheel)
- [x] `pyproject.toml` 配置完成，依赖: `pandas>=2.2`, `numpy>=1.26`
- [x] `uv sync` 安装成功 (pandas=2.3.3, numpy=2.2.6)
- [x] 验证 Bitget API 可达

> **为什么不用 pandas-ta**: 依赖 numba/llvmlite，Python 3.14 构建失败。
> EMA/RSI/MACD/ADX/ATR 用 pandas 原生计算即可，代码量很少。

> **数据源决策**: 统一使用 Bitget API 作为唯一数据源。
> - 优势: 价格与实际交易精确匹配、大宗商品统一处理、无额外依赖
> - 约束: 历史数据最多 90 天日K，不支持 EMA200
> - 适配: 1-2 周持仓周期仅需 EMA20/EMA50，90 天数据完全充足

**运行方式**: 所有脚本通过 `uv run python scripts/xxx.py` 执行，自动使用项目虚拟环境。

---

### 1.2 Bitget 品种同步脚本 (`scripts/sync_bitget_symbols.py`)

- [x] 实现 `sync_bitget_symbols.py` 脚本
  - [x] 调用 Bitget 公开 API: `GET /api/v2/mix/market/contracts?productType=USDT-FUTURES`
  - [x] 过滤 `isRwa == "YES"` 的品种 (即美股/大宗商品合约)
  - [x] 进一步分类: 美股个股 / ETF / 大宗商品 (通过预定义列表区分)
  - [x] 输出 JSON 到 stdout，包含:
    - `total`: 品种总数
    - `symbols`: 品种列表，每个包含:
      - `baseCoin`: 基础代码 (如 NVDA)
      - `symbol`: 交易对 (如 NVDAUSDT)
      - `maxLever`: 最大杠杆
      - `status`: 合约状态
      - `group`: 分组 (stock / etf / commodity)
  - [x] 同时保存到本地缓存文件 `config/bitget_symbols.json`
  - [x] 支持 `--force` 强制刷新，否则缓存 24h 内有效时直接读缓存
  - [x] 无需 API Key (公开接口)
  - [x] 额外: `--group` 过滤, `--quiet` 简洁输出, `lookup_symbol()` 供其他脚本调用
- [x] 测试: `uv run python scripts/sync_bitget_symbols.py --force` 输出完整品种列表 (68 个)
- [x] 测试: 分组统计 stock=50, etf=12, commodity=6
- [x] 测试: 缓存机制正常 (第二次调用 source=cache)
- [x] 测试: `lookup_symbol("NVDA")` 正确返回, `lookup_symbol("INVALID")` 返回 None

**验收标准**: 全部通过。

---

### 1.3 数据获取脚本 (`scripts/fetch_data.py`)

- [x] 实现 `fetch_data.py` 脚本
  - [x] 接收命令行参数: `ticker` (必选), `--days` (可选, 默认 `90`)
  - [x] **品种校验**: 检查 ticker 是否在 Bitget 品种列表中 (读取 `config/bitget_symbols.json`)，不在则报错提示
  - [x] 通过 Bitget API 获取日K数据: `GET /api/v2/mix/market/history-candles`
    - [x] 参数: `symbol=<ticker>USDT`, `productType=USDT-FUTURES`, `granularity=1D`
    - [x] 支持分页拼接获取完整历史 (endTime 迭代)
  - [x] 输出 JSON 到 stdout，包含:
    - `ticker`: 股票代码
    - `source`: "bitget"
    - `data_points`: 数据条数
    - `latest`: 最新一条 OHLCV
    - `status`: "success" / "error"
  - [x] 异常处理: ticker 不存在、网络超时、数据为空
- [x] 测试: `python fetch_data.py NVDA` 输出正确 JSON
- [x] 测试: `python fetch_data.py INVALID_TICKER` 输出错误信息

**验收标准**: 脚本对有效/无效 ticker 均能正确处理并输出结构化 JSON。

---

### 1.4 趋势分析脚本 (`scripts/trend_analysis.py`)

- [x] 实现 `trend_analysis.py` 脚本
  - [x] 接收命令行参数: `ticker` (必选)
  - [x] 内部调用 Bitget API 获取日K数据 (复用 fetch_data 逻辑)
  - [x] 计算以下指标:
    - [x] EMA20, EMA50 (不用 EMA200，90天数据不够)
    - [x] ADX(14)
    - [x] RSI(14)
    - [x] MACD(12,26,9) 及柱状图
    - [x] ATR(14)
    - [x] 相对成交量 (当日量 / 20日均量)
  - [x] 趋势判断 (`determine_trend`): 简化为 2 行核心逻辑
    - [x] `direction`: EMA20 > EMA50 + 价格 > EMA20 → bullish, 反之 bearish, 其余 neutral
    - [x] `strength`: ADX 值 → strong(>25) / moderate(20-25) / weak(<20)
  - [x] Gate 判断:
    - [x] `gate_pass = true`: ADX >= 20 且 direction != "neutral"
    - [x] `gate_pass = false`: 其他情况
  - [x] 延续性评估 (`assess_continuation`): 三因子打分 → verdict
    - [x] 因子 1 — 动能方向: MACD histogram 带符号比较 (结合趋势方向, 修复旧版 abs() 缺陷)
    - [x] 因子 2 — 趋势强化: ADX 是否上升 (对比 3 日前)
    - [x] 因子 3 — 量能确认: volume_ratio >= 1.0
    - [x] verdict: strong(>=2分) / moderate(>=0分) / weakening(<0分)
    - [x] risk_flags: 仅极端信号 (rsi_overbought / rsi_oversold / volume_dry)
  - [x] 关键价位:
    - [x] `support`: EMA20, EMA50 作为支撑参考
    - [x] `resistance`: 近期高点
    - [x] `atr`: ATR 值
  - [x] 输出重组为因果链: trend → continuation → levels → gate → raw
- [x] 测试: NVDA (bullish/strong, continuation=strong, gate=pass, risk=rsi_overbought)
- [x] 测试: COST (bullish/weak, continuation=moderate, gate=fail ADX<20, risk=volume_dry)
- [x] 测试: XAG (bearish/moderate, continuation=strong, gate=pass)

> **重构记录 (2025-04-25)**:
> - 移除: `ema_alignment` (crossed_up/down), `macd_cross`, `rsi_divergence`, `adx_direction`
> - 移除: `determine_trend` 中的三重 neutral 条件 (ema_converged/price_between/contradiction)
> - 修复: MACD histogram 方向判断改为带符号比较 (旧版用 abs() 对比有逻辑缺陷)
> - 新增: `assess_continuation` 三因子打分，输出 verdict + risk_flags
> - 重组: JSON 输出按因果链 trend → continuation → levels → gate → raw

**验收标准**:
1. 输出 JSON 包含所有定义的字段
2. EMA/RSI/MACD 数值与 Bitget 图表一致
3. Gate 判断逻辑正确 (强趋势通过, 震荡不通过)
4. 延续性评估逻辑清晰: 三因子独立可验证

---

### 1.4 SKILL.md 编写

- [x] 创建 `SKILL.md` 文件，包含 YAML frontmatter:
  - [x] `name`: swing-analysis
  - [x] `description`: 包含触发词 (swing, 波段分析, 趋势分析)
- [x] 编写子命令分发逻辑:
  - [x] 识别 `swing trend <ticker>`: 仅运行 trend_analysis.py，格式化展示结果
  - [x] 识别 `swing data <ticker>`: 仅运行 fetch_data.py，展示行情数据
  - [x] 识别 `swing risk --entry X --stop Y`: 仅运行 risk_calculator.py
  - [x] 识别 `swing <ticker>` (无子命令): 执行完整分析流程
- [x] 编写完整流程步骤:
  - [x] Step 1: 运行 fetch_data.py 获取数据
  - [x] Step 2: 运行 trend_analysis.py 获取趋势报告
  - [x] Step 3: Gate 判断 (读取 gate_pass 字段)
  - [x] Step 4: 深度推理 (嵌入分析 Prompt)
  - [x] Step 5: 输出分析报告
- [x] 嵌入 Stage 2 推理 Prompt (波段分析师角色):
  - [x] 趋势确认与定性
  - [x] 趋势延续动力分析
  - [x] 波段机会评估
  - [x] 风控建议 (基础版)
- [x] 定义输出格式模板

**验收标准**: 在 Antigravity 中输入 "swing AAPL"，Agent 能识别 Skill 并按步骤执行。

---

### 1.5 Phase 1 集成测试

- [ ] 完整流程测试: `swing AAPL`
  - [ ] Agent 识别 Skill 并触发
  - [ ] 脚本正确执行并返回数据
  - [ ] Agent 读取 JSON 并进行推理
  - [ ] 输出包含趋势判断 + 动力分析 + 建议
- [ ] 完整流程测试: `swing SPY` (ETF，通常有明确趋势)
- [ ] 子命令测试: `swing trend AAPL`
  - [ ] 仅运行脚本，展示指标数据表格
  - [ ] 不触发 LLM 推理分析
- [ ] 子命令测试: `swing data AAPL`
  - [ ] 仅展示原始行情数据
- [ ] Gate 过滤测试: 找一只震荡股测试，确认 Agent 直接输出 "观望" 而不进行深度推理
- [ ] 错误处理测试: `swing INVALID` 应给出友好错误提示

**验收标准**: 6 个测试用例全部通过，子命令模式不调用推理。

---

## Phase 2: 推理深化

### 2.1 Prompt 优化 (`prompts/swing_analyst.md`)

- [x] 独立 Prompt 文件，从 SKILL.md 引用
- [x] 优化 4 步推理框架:
  - [x] Step 1 趋势定性: 加入趋势阶段判断 (初期突破/中期延续/晚期加速)
  - [x] Step 2 动力分析: 加入多指标矛盾检测逻辑
  - [x] Step 3 机会评估: 加入过度延伸判断 (价格远离均线时发出警告)
  - [x] Step 4 风控: 加入盈亏比计算要求
- [x] 加入 few-shot 示例 (一个多头案例 + 一个观望案例)

**验收标准**: Agent 输出的推理质量明显提升，每一步都有具体数据支撑。

---

### 2.2 风控计算脚本 (`scripts/risk_calculator.py`)

- [x] 实现 `risk_calculator.py` 脚本
  - [x] 接收参数: `--entry`, `--stop`, `--account` (默认 100000), `--risk-pct` (默认 0.02)
  - [x] 计算:
    - [x] `position_size`: 仓位股数 = (account * risk_pct) / (entry - stop)
    - [x] `risk_amount`: 单笔风险金额
    - [x] `max_loss`: 止损时的最大亏损
    - [x] `target_2r`: 2倍盈亏比目标价
    - [x] `target_3r`: 3倍盈亏比目标价
  - [x] 输出 JSON
  - [x] 额外: `--atr` 参数, `stop_atr_multiple` 计算, 做空方向支持
- [x] 测试: 验证仓位计算的数学正确性 (多头: entry=150 stop=142, 空头: entry=100 stop=108)
- [x] 边界测试: entry == stop 时应返回错误

**验收标准**: 仓位计算结果经人工手算验证正确。

---

### 2.3 输出格式标准化

- [x] 定义标准报告模板 (`prompts/output_schema.md`)
- [x] 包含以下板块:
  - [x] 标题栏: 股票代码 + 日期 + 趋势方向标签
  - [x] 趋势判断: 方向 + 阶段 + 数据依据
  - [x] 动力分析: 结论 + 多维指标分析
  - [x] 机会评估: 结论 + 关键价位
  - [x] 风控建议: 入场/止损/目标/仓位/盈亏比
  - [ ] 综合评分: 1-10 分 (可选)
- [x] 在 SKILL.md 中引用此模板

**验收标准**: 不同股票的分析报告格式一致，可读性强。

---

### 2.4 Phase 2 集成测试

- [ ] 测试 NVDA (科技股, 高波动)
- [ ] 测试 JNJ (防御股, 低波动)
- [ ] 测试 SPY (ETF, 市场整体)
- [ ] 验证风控数值是否合理 (仓位不超过总资金 10%)
- [ ] 对比 Agent 分析结论与 TradingView 图表的一致性

**验收标准**: 3 只不同类型标的的分析报告质量均达标。

---

## Phase 3: 扩展能力

### 3.1 批量扫描模式

- [x] SKILL.md 加入批量扫描触发词: "swing scan ..."
- [x] 实现批量逻辑 (`scripts/batch_scan.py`):
  - [x] 接收逗号分隔的多个 ticker
  - [x] 对每个 ticker 运行 Stage 1 (trend_analysis.py)
  - [x] 汇总所有 gate_pass == true 的标的
  - [x] 输出 Markdown 筛选表格 (品种/价格/涨跌/趋势/ADX/RSI/动能/量比/延续/风险/Gate)
  - [x] 支持 `--json` JSON 格式输出
  - [x] 仅对通过标的进行 Stage 2 深度分析 (SKILL.md 已定义)
- [x] 测试: `--group mega_cap` 扫描 7 只 (AAPL,AMZN,GOOGL,META,MSFT,NVDA,TSLA) 全部成功
- [x] 测试: `--group etf` 扫描 12 只, Gate 过滤正常 (4 通过, 8 未通过)

**验收标准**: 批量扫描 7 只股票，正确过滤并对通过标的生成分析报告。 ✅

---

### 3.2 Bitget 品种分组与扫描

- [x] 分组实现在 `batch_scan.py` 中 (复用 sync_bitget_symbols 缓存):
  ```yaml
  all:        # 全部 RWA 品种 (68, 动态从缓存获取)
  stock:      # 美股个股 (50)
  etf:        # ETF (12)
  commodity:  # 大宗商品 (6)
  mega_cap:   # 大盘科技股 (7: AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA)
  ```
- [ ] 支持自定义分组: `config/custom_groups.yaml` (用户手动维护) — 可选
- [x] 扫描命令:
  - [x] `swing scan` -- 扫描全部 RWA 品种 (美股+ETF+大宗商品)
  - [x] `swing scan --group stock` -- 仅扫描美股个股
  - [x] `swing scan --group etf` -- 扫描 ETF (已测试: 12只)
  - [x] `swing scan --group commodity` -- 扫描大宗商品
  - [x] `swing scan --group mega_cap` -- 扫描大盘股 (已测试: 7只)
- [x] 每次扫描前自动检查缓存是否过期，过期则先同步 (get_symbols 内置)

**验收标准**: 分组过滤正确，`swing scan` 默认扫描全部 RWA 品种 (含大宗商品)。 ✅

---

### 3.3 历史对比 (可选)

- [ ] 将每次分析结果缓存到本地文件 (JSON)
- [ ] 下次分析同一标的时，对比上次结果:
  - [ ] 趋势方向是否变化
  - [ ] 动力是增强还是减弱
  - [ ] 关键价位变化
- [ ] 在报告中加入 "与上次对比" 板块

**验收标准**: 对同一标的连续两次分析，第二次报告包含变化对比。

---

### 3.4 VPS 部署 + 项目迁移

- [ ] 初始化 Git 仓库，推送到 GitHub
- [ ] Ubuntu VPS 部署流程:
  ```bash
  # 1. 安装 uv (VPS 上一次性)
  curl -LsSf https://astral.sh/uv/install.sh | sh

  # 2. 克隆 + 安装 (一条命令)
  git clone <repo> && cd trading-agent && uv sync

  # 3. 运行
  uv run python scripts/trend_analysis.py NVDA
  ```
- [ ] `uv.lock` 保证 Windows/Ubuntu 依赖版本完全一致
- [ ] 可选: 配置 cron 定时批量扫描
- [ ] 将 scripts/ 整理为 `src/trading_agent/` 包结构 (可选)

**验收标准**: VPS 上 `uv sync && uv run python scripts/trend_analysis.py NVDA` 一次成功。

---

## Phase 4: 双驱动重构 (2026-04-25)

> **重构动机**: 原始流程偏离用户目标 — 用户要的是"基本面驱动 + 技术面找介入点 + 吃鱼身"，
> 但 Phase 1-3 全是技术面，无法回答"这只值不值得持有 1-2 周"或"是鱼头/鱼身/鱼尾"。

### 4.1 基础设施

- [x] 添加依赖: `yfinance>=0.2.40`, `python-dotenv>=1.0`
- [x] `.env.example` 模板 (FINNHUB_API_KEY)
- [x] `.gitignore` 加 `.env` 和 `config/fundamentals_cache.json`

### 4.2 Stage 0: 基本面叙事层 (`scripts/fundamentals.py`)

- [x] yfinance 主源 + Finnhub 兜底 (财报日历)
- [x] 4 个核心信号:
  - [x] 业绩面: 上次财报 EPS/营收超预期幅度 (yfinance.earnings_history)
  - [x] 预期面: 下次财报日 + 是否在 14 天分析窗口 (yfinance.calendar / Finnhub)
  - [x] 行业面: 动态获取 sector → ETF 趋势 (5d/20d 变化)
  - [x] 评级面: 分析师评级均值 + 目标价隐含上涨空间
- [x] `narrative.score` (0-10) + `narrative.thesis` (strong/moderate/weak)
- [x] 6h TTL 缓存 (`config/fundamentals_cache.json`)
- [x] 半导体行业用 SMH，其他用 SPDR sector ETF
- [x] 测试: NVDA score=7 (strong), TSM score=7 (strong)

### 4.3 Stage 1.5: 鱼身定位 (扩展 `trend_analysis.py`)

- [x] 新增 `locate_fish_body()` 函数:
  - [x] 趋势启动时长: 最近一次 EMA20 穿越 EMA50 距今天数
  - [x] 累计涨跌幅: 从启动点到当前
  - [x] 偏离度: 当前价距 EMA20
  - [x] 阶段标签: early(鱼头) / mid(鱼身) / late(鱼尾) / n/a
  - [x] `ideal_entry` 信号: 阶段 + 偏离 + 累计涨幅联合判断
- [x] 集成到 `build_trend_report()` 输出
- [x] 测试: TSM stage=mid (启动 12 天 累计 +11% 偏离 +10%), NVDA stage=mid (启动 11 天 累计 +11% 偏离 +7.7%)

### 4.4 推理框架重写 (`prompts/swing_analyst.md`)

- [x] 5 步推理框架 (新增 Step 0 基本面审查)
- [x] 决策矩阵: 基本面 × 鱼身 × 动力 → 决策建议
- [x] 4 个 few-shot 示例 (核心持仓 / 等回调 / 不做 / 观望)

### 4.5 输出模板更新 (`prompts/output_schema.md`)

- [x] 完整模板 6 板块 (基本面 / 趋势鱼身 / 动力 / 共振 / 风控)
- [x] 3 个分支模板 (基本面拦截 / Gate 拦截 / 数据缺失)
- [x] 中文映射表

### 4.6 SKILL.md 更新

- [x] 双驱动决策模型流程图
- [x] 新子命令 `swing fund <ticker>`
- [x] 完整流程: Stage 0 → Stage 1 → 整合推理

### 4.7 batch_scan.py 集成

- [x] 新增 `--with-fund` 选项
- [x] 表格新增列: 鱼身 / 叙事 / 上涨空间 / 财报
- [x] 三层共振推荐 (基本面强 + 鱼身位置 + 动力强)
- [x] 大宗商品自动跳过基本面 (无财报概念)
- [x] 测试: mega_cap + --with-fund 7 只全部通过, NVDA 三层共振推荐

### 4.8 验证

- [x] 端到端测试 TSM/NVDA 完整新流程
- [x] mega_cap 批量 + 基本面验证
- [ ] 全量 RWA + 基本面 (慢, 需手动跑)

### 4.9 决策逻辑修正 — 仓位决策模型

> **用户反馈** (2026-04-25): 之前 prompt 中的"等回调"逻辑错误地把"贵位置"当成不入场理由。
> **修正**: 入场决定 = 基本面 + Gate; 仓位大小 = 鱼身阶段; 出局信号 = 仅趋势破位。

- [x] 重写 `swing_analyst.md` Step 3 — 入场矩阵 + 仓位倍数矩阵 + 调整因子
  - [x] 入场矩阵: 基本面 + Gate 决定做/不做
  - [x] 仓位倍数矩阵: 鱼头 1.5× / 鱼身 ideal 1.2× / 鱼身贵 0.6× / 鱼尾 0.4× / 鱼尾衰竭 0×
  - [x] 调整因子: 财报窗口 ×0.5, RSI 超买+鱼尾 ×0.7, 已超目标 ×0.7
- [x] 7 个 few-shot 示例覆盖所有决策分支
- [x] 同步 `output_schema.md` — 报告加"入场决定 + 仓位倍数计算 + 出局信号"板块
- [x] 测试: MU 案例验证 (鱼尾 + RSI 超买 → 0.28× 单笔 0.56% 风险, 但仍入场)

**关键原则**:
1. **入场**: 基本面有故事 + 趋势在 = 做
2. **仓位**: 鱼头/鱼身/鱼尾决定倍数 (1.5× / 1.0× / 0.4×)
3. **出局**: 趋势破位 / 触及止损 / 触及目标 (不因"贵"主动放弃)
4. **加仓**: ideal_entry=false 时等回调到 EMA20 后加到标准仓

### 4.10 文件清理 + 文档完善

- [x] 删除 `main.py` (uv 默认模板)
- [x] 删除 `scripts/check_rwa.py` (一次性测试脚本)
- [x] 删除 `implementation_plan.md` (已被 TODO.md 完全覆盖)
- [x] 创建 `README.md` 项目入口文档

---

## 全局验收标准

| 验收项 | Phase | 标准 |
|--------|-------|------|
| Skill 可触发 | P1 | 输入 "swing AAPL" 能正确触发工作流 |
| 指标准确性 | P1 | EMA/RSI/MACD 与 TradingView 偏差 < 1% |
| Gate 过滤 | P1 | 震荡股不触发深度推理 |
| 推理质量 | P2 | 每步推理有数据依据，结论明确 |
| 风控正确 | P2 | 仓位计算经手算验证 |
| 报告格式 | P2 | 不同标的输出格式一致 |
| 批量扫描 | P3 | 7+ 只股票批量扫描正确过滤 |
| 错误处理 | P1 | 无效 ticker、网络异常均有友好提示 |

---

## 风险与注意事项

1. **Bitget API 限流**: 批量扫描时需加入请求间隔 (1-2秒)，避免被限流
2. **历史数据深度**: Bitget RWA 合约上线时间短，最多约 90 天日K，不支持 EMA200
3. **指标偏差**: pandas_ta 部分指标算法与 Bitget/TradingView 可能有微小差异，需实测确认
4. **Skill 触发**: 需确认 Antigravity 的 Skill 匹配机制，确保触发词不与其他 Skill 冲突
5. **24h 交易**: Bitget 合约全天候交易，日K截断时间可能与美股收盘不同，注意 K 线形态差异
