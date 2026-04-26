# Agent 智能体分析框架优化方案与 TODO

> 目标: 将当前项目从“交易分析脚本包 + Skill 说明”升级为“可独立运行、可测试、可由 Agent 调度的波段分析框架”。
>
> 核心思想: 脚本负责稳定地产生数据、因子、决策和风控；Agent 负责调度、解释、追问和报告表达。

---

## 1. 初始目标复盘

用户原始目标不是单纯做一个技术分析脚本，而是构建一个 Agent 智能体分析框架:

```text
1. Agent 先调用脚本批量扫描商品/股票/ETF
2. 从中筛出具备趋势形态的候选标的
3. 针对候选标的分析逻辑强度、业绩增量、趋势持续性
4. 判断能否介入波段
5. 若已介入或继续跟踪，则持有到趋势破位或逻辑明显转弱
```

当前项目已经完成了趋势扫描、技术 Gate、鱼身定位、基本面初筛、风控计算等基础能力，但完整的 Agent 编排层仍然偏弱。

---

## 2. 当前项目与目标的差距

### 已经对齐的部分

- `scanner.py` 已能批量扫描 Bitget RWA 品种，并筛出 `gate_pass=true` 的趋势候选。
- `trend.py` 已能输出趋势方向、ADX、鱼身阶段、延续动力、风险标记。
- `fundamentals.py` 已能输出基本面叙事分数，包括 EPS surprise、行业 ETF、评级、目标价和财报窗口。
- `risk.py` 已能根据入场价、止损价、账户规模计算仓位和盈亏比。
- `prompts/swing_analyst.md` 已经体现“基本面 + 技术面 + 鱼身 + 趋势破位退出”的核心策略思想。

### 主要偏离点

1. **完整分析流程没有代码入口**
   - 现在 `fund -> trend -> decision -> risk -> report` 的完整流程主要写在 `SKILL.md` 和 prompt 中。
   - 终端用户需要分步调用，Agent 也缺少一个稳定的结构化入口。

2. **逻辑强度仍是基本面叙事，不是独立状态指标**
   - 当前 `narrative.score` 是静态分数。
   - 缺少 `logic_strength` 当前值和 `logic_trend` 变化方向。
   - 无法直接回答“逻辑是在逐步加强还是逐步减弱”。

3. **仓位和介入决策主要存在于 prompt**
   - Prompt 中有仓位矩阵和调整因子，但代码层不可测试、不可复现。
   - Agent 每次推理可能产生轻微漂移。

4. **缺少持仓/观察状态**
   - 当前只能分析“此刻是否适合做”。
   - 缺少“上次分析是什么状态、本次是否破位、逻辑是否转弱、是否继续持有”的跟踪能力。

5. **CLI 与文档不完全一致**
   - `SKILL.md` 中提到 `report`，但当前 `cli.py` 没有 `report` 命令。
   - 需要先统一用户可用入口。

---

## 3. 优化方向

### 3.1 总体原则

```text
代码负责判断，Agent 负责解释。
脚本输出结构化结果，Prompt 不承担核心业务规则。
Agent 可以调度多个步骤，但每一步都应该有可复现的 Python 入口。
```

### 3.2 目标分层架构

```text
数据层
- Bitget K 线
- Bitget RWA 品种列表
- yfinance 基本面
- Finnhub 财报日历

因子层
- 技术因子: EMA / ADX / RSI / MACD / ATR / volume ratio
- 逻辑因子: 业绩增量 / 行业景气 / 预期修正 / 催化剂 / 价格验证

分析层
- TrendReport: 趋势形态、Gate、鱼身阶段、延续动力
- LogicReport: 逻辑强度、逻辑变化、驱动因素、风险因素
- RiskReport: 仓位、止损、目标、盈亏比

决策层
- DecisionReport: 是否介入、是否继续持有、仓位倍数、调整因子、退出条件

编排层
- analyze: 单标的完整分析
- research: 扫描后对候选标的深度研究
- monitor: 对观察/持仓标的做持续跟踪

交互层
- CLI
- Agent Skill
- Markdown 报告
- 后续可扩展 HTML 报告、定时任务、推送
```

---

## 4. 逻辑强度引擎设计

### 4.1 目标输出

新增 `LogicReport`，核心字段如下:

```json
{
  "status": "success",
  "ticker": "NVDA",
  "generated_at": "2026-04-26T00:00:00Z",
  "logic": {
    "score": 72,
    "grade": "strong",
    "trend": "strengthening",
    "delta": 8,
    "previous_score": 64,
    "confidence": 0.76,
    "drivers": [
      "EPS 超预期 +12.4%",
      "半导体板块 20d +8.1%",
      "目标价仍有 +18.5% 空间"
    ],
    "weaknesses": [
      "财报窗口临近",
      "部分估值空间已被定价"
    ],
    "factor_scores": {
      "earnings_delta": 28,
      "sector_theme": 16,
      "expectation_revision": 14,
      "catalyst": 8,
      "price_confirmation": 6
    }
  }
}
```

### 4.2 逻辑强度评分

逻辑强度采用 0-100 分，便于观察变化。

初版权重:

| 因子 | 权重 | 含义 |
|------|-----:|------|
| 业绩增量 | 35 | EPS/营收超预期、增长改善、利润率变化 |
| 行业/主题景气 | 20 | sector ETF / theme ETF 5d、20d 趋势 |
| 预期修正/机构共识 | 20 | 评级、目标价空间、分析师预期变化 |
| 催化剂窗口 | 15 | 财报前后、产品、政策、行业事件 |
| 价格验证 | 10 | 股价是否验证逻辑、是否强于行业或大盘 |

分级建议:

```text
score >= 75: very_strong
score >= 60: strong
score >= 45: moderate
score < 45: weak
```

### 4.3 逻辑变化判断

新增本地历史文件:

```text
config/logic_history.json
```

每次完整分析后保存逻辑强度快照:

```json
{
  "NVDA": [
    {
      "date": "2026-04-24",
      "score": 64,
      "grade": "strong",
      "drivers": ["EPS beat", "sector bullish"],
      "weaknesses": ["valuation rich"]
    },
    {
      "date": "2026-04-26",
      "score": 72,
      "grade": "strong",
      "drivers": ["sector stronger", "upside remains"],
      "weaknesses": ["earnings window"]
    }
  ]
}
```

变化规则:

```text
delta >= +8: strengthening
delta <= -8: weakening
otherwise: stable
```

连续趋势规则:

```text
最近 3 次分数持续上升: strengthening
最近 3 次分数持续下降: weakening
分数窄幅波动: stable
历史不足: unknown
```

### 4.4 交易决策中的使用方式

逻辑强度不是替代趋势，而是辅助判断“值不值得介入或继续持有”。

建议规则:

```text
新介入:
- Gate PASS
- logic.score >= 60
- logic.trend != weakening

小仓试单:
- Gate PASS
- logic.score 50-59
- logic.trend == strengthening 或 stable

观察:
- Gate PASS 但 logic.trend == weakening
- 或 logic.score < 50

继续持有:
- Gate PASS
- logic.score >= 50
- logic.trend == stable 或 strengthening

减仓:
- Gate PASS
- logic.trend == weakening
- 尤其是鱼尾阶段或动力转弱时

退出:
- Gate FAIL 是主退出信号
- logic.score 大幅下滑 + continuation.weakening 可作为提前降仓或退出确认
```

---

## 5. 新增模块建议

### 5.1 `src/trading_agent/logic.py`

职责:

- 从基本面数据提取逻辑因子。
- 计算 `logic.score`、`logic.grade`、`logic.confidence`。
- 生成 drivers / weaknesses。
- 读取历史快照，计算 `logic.trend` 和 `delta`。

### 5.2 `src/trading_agent/history.py`

职责:

- 统一管理 `logic_history.json`。
- 后续也可扩展为 `analysis_history.json`。
- 提供 `append_snapshot()`、`get_recent_snapshots()`。

### 5.3 `src/trading_agent/decision.py`

职责:

- 输入 `TrendReport + LogicReport + RiskReport`。
- 输出 `DecisionReport`。
- 将仓位矩阵、调整因子、介入/持有/减仓/退出规则代码化。

### 5.4 `src/trading_agent/analyzer.py`

职责:

- 单标的完整编排。
- 流程:

```text
fundamentals -> logic -> trend -> decision -> risk -> report
```

- 支持 JSON 和 Markdown 输出。

### 5.5 `src/trading_agent/reporter.py`

职责:

- 将结构化报告渲染为 Markdown。
- Agent 可以直接读取 JSON，也可以复用 Markdown 报告。

### 5.6 `src/trading_agent/watchlist.py` 或 `state.py`

职责:

- 管理观察池和持仓池。
- 记录每个 ticker 的状态: watchlist / candidate / holding / exited。
- 支持后续 `monitor` 命令。

---

## 6. CLI 目标形态

保留现有命令:

```powershell
uv run trading-agent sync
uv run trading-agent data NVDA
uv run trading-agent trend NVDA
uv run trading-agent fund NVDA
uv run trading-agent risk --entry 209 --stop 195
uv run trading-agent scan --group mega_cap --with-fund
```

新增核心命令:

```powershell
uv run trading-agent analyze NVDA
uv run trading-agent analyze NVDA --json
uv run trading-agent analyze NVDA --account 50000 --risk-pct 0.01
```

新增扫描后研究命令:

```powershell
uv run trading-agent research --group mega_cap
uv run trading-agent research --group stock --limit 5
uv run trading-agent research AAPL,MSFT,NVDA
```

后续新增监控命令:

```powershell
uv run trading-agent monitor
uv run trading-agent monitor --holding
uv run trading-agent watch add NVDA
uv run trading-agent watch list
```

---

## 7. Agent Skill 优化方向

Skill 不再承载核心业务规则，而是变成薄封装。

### Skill 负责

- 识别用户意图。
- 选择合适 CLI 命令。
- 调用 `analyze`、`research`、`monitor`。
- 对结构化结果做自然语言解释。
- 必要时追问账户规模、风险比例、是否已有持仓。

### Skill 不再负责

- 临场计算仓位矩阵。
- 临场判断逻辑强弱。
- 手动串联多个脚本产生不可复现流程。

### 推荐 Agent 工作流

```text
用户: 帮我扫描今天适合波段的标的

Agent:
1. uv run trading-agent research --group all --with-fund --json
2. 读取候选标的 DecisionReport
3. 按 logic.score、logic.trend、Gate、鱼身阶段排序
4. 输出 Top candidates
5. 对用户关注的标的再展开完整 analyze 报告
```

---

## 8. TODO List

### Phase 0: 对齐文档与现状

- [ ] 检查 `README.md`、`SKILL.md`、`TODO.md` 与实际 CLI 是否一致。
- [ ] 移除或标记暂未实现的 `report` 命令说明。
- [ ] 明确当前可用命令和未来规划命令。
- [ ] 将“Agent 负责解释、代码负责判断”的原则写入 README。

验收标准:

- 用户照 README 执行不会遇到不存在的命令。
- Skill 文档不再暗示未实现能力已经可用。

### Phase 1: 新增单标的完整分析入口

- [ ] 新建 `src/trading_agent/analyzer.py`。
- [ ] 实现 `build_analysis_report(ticker, account, risk_pct)`。
- [ ] 串联 `fundamentals -> trend -> risk`，先不引入复杂逻辑历史。
- [ ] 新增 CLI 命令 `analyze <TICKER>`。
- [ ] 支持 `--json` 输出完整结构化结果。
- [ ] 支持 Markdown 简报输出。
- [ ] 为 `analyze` 增加基础测试。

验收标准:

```powershell
uv run trading-agent analyze NVDA
uv run trading-agent analyze NVDA --json
```

均能稳定输出完整分析，不需要 Agent 手动串脚本。

### Phase 2: 逻辑强度引擎

- [ ] 新建 `src/trading_agent/logic.py`。
- [ ] 从 `fundamentals.py` 提取逻辑因子。
- [ ] 将 `narrative.score` 升级或映射为 `logic.score` 0-100。
- [ ] 输出 `logic.grade`。
- [ ] 输出 `logic.drivers` 和 `logic.weaknesses`。
- [ ] 输出 `factor_scores`。
- [ ] 设计 `confidence` 规则，数据缺失时降低置信度。
- [ ] 为强逻辑、中性逻辑、弱逻辑分别写测试。

验收标准:

- `logic.score` 可独立复现。
- Agent 不需要自行判断逻辑强弱，只解释 `LogicReport`。

### Phase 3: 逻辑变化跟踪

- [ ] 新建 `src/trading_agent/history.py`。
- [ ] 新增 `config/logic_history.json`，并加入 `.gitignore`。
- [ ] 每次 `analyze` 后保存逻辑快照。
- [ ] 实现 `previous_score`、`delta`、`logic.trend`。
- [ ] 支持最近 3 次快照判断 strengthening / stable / weakening。
- [ ] 支持 `--no-save-history`，用于测试或临时分析。
- [ ] 为历史不足、分数加强、分数减弱、分数稳定写测试。

验收标准:

- 连续分析同一标的时，报告能说明逻辑是在加强、稳定还是减弱。

### Phase 4: 决策引擎代码化

- [ ] 新建 `src/trading_agent/decision.py`。
- [ ] 将介入规则代码化:
  - [ ] Gate PASS + logic.score >= 60 + logic.trend != weakening。
  - [ ] Gate PASS + logic.score 50-59 可小仓试单。
  - [ ] Gate FAIL 直接观察。
- [ ] 将持有规则代码化:
  - [ ] Gate PASS + logic stable/strengthening 继续持有。
  - [ ] Gate PASS + logic weakening 减仓或谨慎。
  - [ ] Gate FAIL 退出或不介入。
- [ ] 将仓位矩阵代码化:
  - [ ] 鱼头 + ideal_entry + strong continuation。
  - [ ] 鱼身 + ideal_entry。
  - [ ] 鱼身贵位置。
  - [ ] 鱼尾轻仓。
  - [ ] 鱼尾 + weakening 拒绝。
- [ ] 将调整因子代码化:
  - [ ] moderate logic 折扣。
  - [ ] 财报催化剂。
  - [ ] RSI 超买 + 鱼尾。
  - [ ] 目标价空间为负。
- [ ] 输出 `DecisionReport`。
- [ ] 为每个决策分支写单元测试。

验收标准:

- Prompt 中的核心决策矩阵全部能在 Python 测试中验证。
- Agent 输出不再影响实际决策结果。

### Phase 5: 扫描后深度研究

- [x] 新建或扩展 `research` 命令。
- [x] 先调用 `scanner.py` 扫描趋势候选。
- [x] 只对 `gate_pass=true` 的标的调用 `analyze`。
- [x] 支持 `--group`、`--limit`、`--with-fund`、`--json`。
- [x] 按以下优先级排序:
  - [x] logic.score 高。
  - [x] logic.trend strengthening。
  - [x] fish_body early/mid。
  - [x] continuation strong。
  - [x] ideal_entry true。
- [x] 输出候选排名表。
- [x] 输出 Top N 的简版分析。

验收标准:

```powershell
uv run trading-agent research --group mega_cap --limit 3
```

能完成“扫描 -> 候选 -> 深度分析 -> 排名”的 Agent 研究流程。

### Phase 6: 观察池与持仓监控

- [x] 新建 `src/trading_agent/state.py` 或 `watchlist.py`。
- [x] 支持添加观察标的。
- [x] 支持标记持仓标的及入场价、止损价、初始逻辑分。
- [x] 新增 `watch add/list/remove` 命令。
- [x] 新增 `monitor` 命令。
- [x] `monitor` 输出:
  - [x] Gate 是否仍 PASS。
  - [x] logic.score 是否下降。
  - [x] logic.trend 是否 weakening。
  - [x] continuation 是否 weakening。
  - [x] 是否触发止损或趋势破位。
- [x] 输出继续持有、减仓、退出、继续观察建议。

验收标准:

- 框架可以回答“这只已经介入的票是否还能继续持有”。

### Phase 7: Skill 薄封装重构

- [ ] 精简 `SKILL.md`。
- [ ] 将完整分析调用改为 `uv run trading-agent analyze <TICKER> --json`。
- [ ] 将批量扫描调用改为 `uv run trading-agent research ... --json`。
- [ ] 将持仓跟踪调用改为 `uv run trading-agent monitor --json`。
- [ ] Prompt 只保留报告表达、风险声明、用户沟通风格。
- [ ] 移除 Skill 中重复的业务矩阵，改为解释 `DecisionReport`。

验收标准:

- Agent Skill 不再手动拼接业务逻辑。
- 同一 ticker 在 CLI 和 Agent 中得到一致决策。

### Phase 8: 报告与验证

- [ ] 新建 `src/trading_agent/reporter.py`。
- [ ] 标准化 Markdown 报告:
  - [ ] 当前结论。
  - [ ] 趋势形态。
  - [ ] 逻辑强度与变化。
  - [ ] 趋势持续性。
  - [ ] 介入/持有/减仓/退出建议。
  - [ ] 风控价位。
- [ ] 新增端到端测试:
  - [ ] 强逻辑 + Gate PASS。
  - [ ] 弱逻辑 + Gate PASS。
  - [ ] 强逻辑 + Gate FAIL。
  - [ ] 逻辑减弱 + 鱼尾。
  - [ ] 已持仓 + Gate FAIL。
- [ ] 增加快照测试，防止报告字段意外变化。

验收标准:

- 报告格式稳定。
- 每个核心决策分支都有测试覆盖。

---

## 9. 推荐实施顺序

优先级从高到低:

```text
1. Phase 0: 文档/CLI 对齐
2. Phase 1: analyze 单标的完整入口
3. Phase 2: logic.score 当前逻辑强度
4. Phase 3: logic.trend 逻辑变化
5. Phase 4: decision.py 决策代码化
6. Phase 5: research 扫描后深度研究
7. Phase 6: monitor 持仓/观察跟踪
8. Phase 7: Skill 薄封装
9. Phase 8: 报告和端到端测试
```

最小可用重构目标:

```text
analyze + logic.score + logic.trend + decision.py
```

只要这四块完成，项目就会从“分析脚本包”明显升级为“Agent 可调度的智能体分析框架”。

---

## 10. 最终形态示例

### 扫描今日机会

```powershell
uv run trading-agent research --group all --limit 5
```

输出:

```text
Top Candidates

1. NVDA
   Gate: PASS
   Logic: 78 / strengthening
   Fish: mid / ideal_entry=false
   Continuation: strong
   Decision: 可小仓介入，回踩 EMA20 加仓

2. TSM
   Gate: PASS
   Logic: 74 / stable
   Fish: early / ideal_entry=true
   Continuation: strong
   Decision: 标准仓介入
```

### 单标的分析

```powershell
uv run trading-agent analyze NVDA
```

输出:

```text
NVDA 波段分析

当前结论: 可介入，但因位置偏贵，建议 0.6x 试单。
逻辑强度: 72 / strong，较上次 +8，趋势 strengthening。
趋势形态: Gate PASS，鱼身 mid，ADX 28。
持续性: strong，MACD 扩张，量能确认。
持有原则: 只要 Gate 不破且逻辑不转弱，可继续持有到 EMA20 破位。
```

### 持仓监控

```powershell
uv run trading-agent monitor --holding
```

输出:

```text
NVDA
- Gate: PASS
- Logic: 72 -> 68，stable
- Continuation: moderate
- Decision: 继续持有，若跌破 EMA20 或 logic_trend 转 weakening 则减仓
```

---

## 11. 核心结论

当前项目策略思想没有偏离，但产品形态还偏“脚本工具”。

下一阶段应该围绕三个核心问题重构:

```text
1. 这只标的当前有没有趋势形态？
2. 这只标的逻辑强度是多少，正在加强还是减弱？
3. 基于趋势 + 逻辑 + 持仓状态，应该介入、持有、减仓还是退出？
```

当这三个问题都能由代码稳定输出结构化答案时，Agent 才真正成为智能体研究员，而不是临时调用脚本的报告生成器。

---

## 12. 当前落地状态 (2026-04-26)

本轮已完成最小可用 Agent 编排闭环:

- [x] 新增 `logic.py`: 输出 `LogicReport`，包含 `logic.score`、`logic.grade`、`logic.trend`、`logic.delta`、`confidence`、`drivers`、`weaknesses`、`factor_scores`。
- [x] 新增 `history.py`: 管理 `config/logic_history.json`，支持历史快照、最近记录读取、逻辑趋势推断。
- [x] 新增 `decision.py`: 将介入、小仓、观察、拒绝、减仓等规则代码化，输出 `DecisionReport`。
- [x] 新增 `analyzer.py`: 提供单标的完整编排入口 `analyze`。
- [x] 新增 `reporter.py`: 将结构化 `AnalysisReport` 渲染为 Markdown 报告。
- [x] CLI 接入 `uv run trading-agent analyze <TICKER>`。
- [x] `.gitignore` 忽略 `config/logic_history.json` 和测试临时目录。
- [x] 新增测试覆盖 `history`、`logic`、`decision`、`analyzer`。

验证结果:

```text
uv run pytest -q
76 passed

uv run ruff check .
All checks passed

uv run trading-agent analyze --help
可正常加载新增 CLI
```

已继续完成后续 MVP:

- [x] 新增 `research.py`: 支持扫描后仅对 Gate 通过标的做完整分析，并按决策、逻辑强度、鱼身阶段、延续性、ideal_entry、仓位倍数排序。
- [x] 新增 `state.py`: 管理 `state/trading_state.json`，支持观察池与持仓状态。
- [x] 新增 `monitor.py`: 对观察池和持仓执行持续监控，输出止损、Gate、逻辑转弱、延续性转弱告警。
- [x] CLI 接入 `research`、`watch`、`holding`、`monitor`。
- [x] 新增测试覆盖 `research`、`state`、`monitor`。
- [x] `analyze` 支持 `degraded` 状态，基本面/逻辑临时失败时保留技术面结果并显式输出 warnings。

下一步建议优先继续:

```text
1. Hermes/cron 定时调用 research 与 monitor
2. reports/YYYY-MM-DD 报告归档
3. 通知通道 (邮件/Telegram/企业微信等)
4. HTML/report 命令或仪表盘
```
