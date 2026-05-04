# 美股情绪指标开发计划

## 1. 背景与目标

本项目现有主线是基于 Bitget RWA 合约做美股波段分析与交易候选筛选。新的美股情绪指标用于补充“市场环境”判断：

```text
yfinance 美股前排个股 = 情绪参考池
Bitget RWA 美股个股 = 实际交易池
```

核心目标：

- 用更宽的美股活跃股票池判断市场风险偏好，而不是只用 Bitget 可交易股票池自我统计。
- 捕捉市场从冰点到回暖的状态变化，辅助仓位开关和候选优先级。
- 输出可测试、可复盘、可解释的结构化情绪报告。
- 第一版不追求复杂预测模型，优先做稳定可靠的价格行为和市场广度指标。

关联设计文档：

```text
docs/us_stock_sentiment_attack_pullback.md
```

## 2. 第一版范围

第一版只做四个核心模块：

```text
1. 攻击波 / 回头波
2. 市场广度
3. 新高新低
4. MA20 均线修复
```

暂不纳入：

```text
VIX / PutCall
高 beta / 低 beta 轮动
short squeeze
社媒或文本情绪
AAII / NAAIM 调查情绪
盘中分钟级情绪
```

这些后续可作为确认层，不进入 MVP。

### 2.1 最佳实践复核

本计划按以下量化研究与工程最佳实践做约束：

```text
1. 数据源分层：
   ticker master 不依赖 yfinance 搜索；yfinance 只负责 OHLCV。

2. Point-in-time：
   股票池选择只使用 t-1 以前可见数据，避免当天成交额和当天成分污染。

3. 时间序列验证：
   不做随机 train/test split；使用 walk-forward 或 TimeSeriesSplit 风格验证。

4. 参数冻结：
   阈值、状态机、参考池规模先在训练区间确定，再到样本外区间验证。

5. 过拟合控制：
   第一版只保留少量指标，不进行大规模参数搜索。

6. 可复现：
   缓存原始输入、参数、股票池成分和输出结果，保证同一天报告可复算。

7. 风险披露：
   回测结果只作为研究，不当作实盘收益承诺。
```

优化后的 MVP 原则：

```text
少指标、强约束、可复现、先样本外验证，再考虑复杂化。
```

## 3. 指标体系

### 3.1 攻击波 / 回头波

单票基础字段：

```text
O = open
H = high
L = low
C = close
```

核心因子：

```text
AttackAmp = H / O - 1
PullbackAmp = H / C - 1
AttackHold = (C - O) / (H - O)
Giveback = (H - C) / (H - O)
BullBodyRatio = (C - O) / (H - L)
BearHold = (O - C) / (O - L)
BearBodyRatio = (O - C) / (H - L)
```

默认定义：

```text
PureAttack =
    AttackAmp >= 3%
    and C > O
    and AttackHold >= 0.5
    and BullBodyRatio >= 0.30

FailedAttack =
    AttackAmp >= 3%
    and PullbackAmp >= 3%
    and Giveback >= 0.5

PurePullback =
    PullbackAmp >= 3%
    and C < O
    and BearHold >= 0.5
    and BearBodyRatio >= 0.30
```

聚合指标：

```text
RawAttackRatio
PureAttackRatio
FailedAttackRatio
PurePullbackRatio
NetAttackSentiment = PureAttackRatio - PurePullbackRatio
AttackQuality = PureAttackRatio / RawAttackRatio
AttackFailureRate = FailedAttackRatio / RawAttackRatio
```

### 3.2 市场广度

用于判断上涨是否扩散：

```text
AdvanceRatio = 上涨股票数 / 有效样本数
DeclineRatio = 下跌股票数 / 有效样本数
UpDollarVolumeRatio = 上涨股票成交额 / 总成交额
DownDollarVolumeRatio = 下跌股票成交额 / 总成交额
```

可选：

```text
EqualWeightReturn = 股票池等权日收益
MedianReturn = 股票池收益中位数
```

### 3.3 新高新低

用于判断冰点是否止血：

```text
High20Ratio = 创 20 日新高股票数 / 有效样本数
Low20Ratio = 创 20 日新低股票数 / 有效样本数
NetHighLow20 = High20Ratio - Low20Ratio
Low20Slope3 = EMA(Low20Ratio, 3) - EMA(Low20Ratio, 3).shift(3)
```

第一版只做 20 日新高新低。52 周新高新低等数据需要更长历史，放到后续。

### 3.4 MA20 修复

用于判断趋势结构是否从弱转稳：

```text
AboveMA20Ratio = close > MA20 的股票数 / 有效样本数
ReclaimMA20Ratio = 当日从 MA20 下方重新站上 MA20 的股票数 / 有效样本数
LoseMA20Ratio = 当日从 MA20 上方跌破 MA20 的股票数 / 有效样本数
```

## 4. 冰点回暖状态机

### 4.1 派生趋势指标

对核心指标计算 3 日 EMA、3 日斜率和 90 日历史分位：

```text
NetAttackEMA3
PurePullbackEMA3
FailureEMA3
Low20EMA3
AboveMA20EMA3

NetAttackSlope3
PullbackSlope3
FailureSlope3
Low20Slope3
AboveMA20Slope3

NetAttackPctRank90
PureAttackPctRank90
PurePullbackPctRank90
FailurePctRank90
Low20PctRank90
AboveMA20PctRank90
```

### 4.2 状态定义

初版状态：

```text
RISK_OFF:
    回头波、新低或失败率处于高分位，且净攻击情绪继续恶化。

COLD:
    有效攻击低，回头波或新低高，但恶化速度放缓。

RECOVERY_CANDIDATE:
    近期出现过 COLD，回头波和新低开始下降，净攻击斜率转正。

RISK_ON:
    有效攻击回到中高分位，失败率不高，广度和 MA20 修复同步改善。

DIVERGENCE:
    攻击多但失败也多，或 Top200 强而 Top500 弱。
```

### 4.3 冰点回暖候选

推荐初版规则：

```text
ColdPoint =
    PureAttackPctRank90 <= 20
    and (
        PurePullbackPctRank90 >= 80
        or FailurePctRank90 >= 80
        or Low20PctRank90 >= 80
        or NetAttackPctRank90 <= 20
    )

RecoveryCandidate =
    ColdPoint 在过去 5 个交易日内出现过
    and NetAttackSlope3 > 0
    and PullbackSlope3 < 0
    and FailureSlope3 <= 0
    and Low20Slope3 < 0
    and AboveMA20Slope3 >= 0
```

确认规则：

```text
RecoveryConfirmed =
    RecoveryCandidate
    and PureAttackPctRank90 >= 40
    and FailurePctRank90 <= 60
    and AdvanceRatio >= 0.50
    and AboveMA20Slope3 > 0
```

## 5. 数据设计

### 5.1 参考池

参考池来自 yfinance 日线 OHLCV：

```text
ReferenceUniverse_t =
    从美股 ticker master 中排除 ETF、权证、优先股等非普通股；
    用 t-1 以前的过去 20 个交易日平均成交额排序；
    取 Top200 作为主参考池；
    同时计算 Top100 / Top500 作为宽窄对照。
```

成交额：

```text
dollar_volume = close * volume
```

注意：

- 不使用当天成交额选择当天股票池，避免未来函数。
- yfinance 可用于 OHLCV，但不作为唯一 ticker master 来源。
- 第一版 ticker master 优先来自 Nasdaq Trader symbol directory 的 `nasdaqlisted.txt` 和 `otherlisted.txt`，再做本地过滤。
- 第一版可以先用静态 ticker master 文件，但文件必须记录生成日期、来源和过滤规则。
- OHLC 调整口径必须一致，不混用 raw open/high/low 和 adjusted close。
- 若使用当前静态股票池回测历史，必须标记为“当前成分回测”，不能声称是无幸存者偏差回测。

推荐 ticker master 字段：

```text
ticker
name
exchange
asset_type
is_etf
is_test_issue
financial_status
source
source_file_time
generated_at
active
```

MVP 过滤规则：

```text
保留:
    普通股、ADR 可配置保留。

排除:
    ETF、杠杆 ETF、基金、权证、优先股、unit、test issue、非 normal financial status。
```

### 5.2 交易池

交易池来自 Bitget RWA：

```text
config/bitget_symbols.json
group == stock
```

交易池用途：

- 输出当前可交易股票列表。
- 映射参考池情绪到 Bitget 候选优先级。
- 后续评估参考池情绪对 Bitget 交易池等权收益、扫描通过率和回撤的影响。

交易池不参与参考池情绪统计。

### 5.3 缓存文件

建议新增：

```text
config/us_equity_universe.json
config/sentiment_cache.json
```

`.gitignore` 建议忽略：

```text
config/sentiment_cache.json
config/yfinance_price_cache/
```

`config/us_equity_universe.json` 是否提交取决于来源许可和维护方式。第一版若为手工整理的较小列表，可以提交；若来自下载数据源，应确认许可。

### 5.4 数据质量门槛

每次生成情绪报告前必须做数据质量检查：

```text
effective_count >= top_n * 0.90
最近交易日缺失率 <= 10%
OHLC 中 open/high/low/close 全部为正
high >= max(open, close)
low <= min(open, close)
volume >= 0
单票异常涨跌幅超过阈值时记录 warning
```

如果有效样本不足：

```text
status = "partial"
state 可以输出，但 risk_mode 不应提高到 aggressive
warnings 必须说明缺失比例和缺失 ticker 示例
```

## 6. 模块设计

### 6.1 新增文件

```text
src/trading_agent/sentiment.py
tests/test_sentiment.py
docs/us_stock_sentiment_development_plan.md
```

可选后续拆分：

```text
src/trading_agent/yfinance_data.py
tests/test_yfinance_data.py
```

### 6.2 sentiment.py 纯函数

优先实现纯函数，降低测试难度：

```text
SentimentParams
    attack_threshold
    pullback_threshold
    hold_threshold
    body_ratio_threshold
    universe_lookback_days
    percentile_lookback_days
    smooth_span

compute_bar_factors(row, params) -> dict
compute_factor_frame(price_frame, params) -> DataFrame
select_reference_universe(price_frame, as_of_date, top_n, params, master=None) -> list[str]
aggregate_daily_sentiment(factor_frame, price_frame, date, universe, params) -> dict
compute_sentiment_history(price_frame, dates, top_n, params) -> DataFrame
classify_sentiment_state(history, params) -> dict
build_market_sentiment_report(...) -> dict
```

### 6.3 yfinance 数据函数

第一版可以先支持手工 ticker 列表：

```text
fetch_yfinance_ohlcv(tickers, start, end, auto_adjust=True) -> DataFrame
```

后续再加入：

```text
load_us_equity_master(path) -> DataFrame
refresh_us_equity_master(...)
cache_price_frame(...)
```

### 6.4 CLI

新增命令：

```text
uv run trading-agent sentiment
uv run trading-agent sentiment --date 2026-05-01
uv run trading-agent sentiment --top 200
uv run trading-agent sentiment --compare 100,500
uv run trading-agent sentiment --tickers config/us_equity_universe.json
uv run trading-agent sentiment --json
```

第一版 CLI 行为：

- 默认计算最近一个 yfinance 可用交易日。
- 默认主参考池 Top200。
- 输出简表和状态说明。
- `--json` 输出完整结构化报告。

## 7. 输出报告

### 7.1 JSON 结构

```json
{
  "status": "success",
  "date": "2026-05-01",
  "source": "yfinance",
  "reference": {
    "top_n": 200,
    "lookback_days": 20,
    "effective_count": 198
  },
  "metrics": {
    "raw_attack_ratio": 0.18,
    "pure_attack_ratio": 0.11,
    "failed_attack_ratio": 0.06,
    "pure_pullback_ratio": 0.08,
    "advance_ratio": 0.54,
    "up_dollar_volume_ratio": 0.61,
    "high20_ratio": 0.07,
    "low20_ratio": 0.05,
    "above_ma20_ratio": 0.48,
    "net_attack_sentiment": 0.03,
    "attack_quality": 0.61,
    "attack_failure_rate": 0.33
  },
  "trend": {
    "state": "RECOVERY_CANDIDATE",
    "net_attack_slope_3": 0.05,
    "pullback_slope_3": -0.04,
    "failure_slope_3": -0.02,
    "low20_slope_3": -0.03,
    "above_ma20_slope_3": 0.04
  },
  "breadth_compare": {
    "top100_state": "RISK_ON",
    "top200_state": "RECOVERY_CANDIDATE",
    "top500_state": "COLD"
  },
  "trade_mapping": {
    "bitget_stock_count": 57,
    "suggested_risk_mode": "normal",
    "notes": [
      "Reference recovery is concentrated in large caps."
    ]
  },
  "warnings": []
}
```

### 7.2 简表输出

CLI 简表建议包含：

```text
date
state
PureAttackRatio
FailedAttackRatio
PurePullbackRatio
AdvanceRatio
Low20Ratio
AboveMA20Ratio
Top100/Top200/Top500 状态
仓位环境建议
```

## 8. 测试计划

### 8.1 单元测试

必须不依赖网络。

测试文件：

```text
tests/test_sentiment.py
```

覆盖：

```text
1. PureAttack 判定
2. FailedAttack 判定
3. PurePullback 判定
4. H <= O、L >= O、H == L、价格缺失、价格为 0 的边界
5. RawAttackRatio / PureAttackRatio / FailedAttackRatio / PurePullbackRatio 聚合
6. AdvanceRatio / UpDollarVolumeRatio 聚合
7. High20Ratio / Low20Ratio 计算
8. AboveMA20Ratio / ReclaimMA20Ratio 计算
9. t-1 股票池选择，防止当天成交额暴增进入当天参考池
10. COLD -> RECOVERY_CANDIDATE -> RISK_ON 状态转换
```

### 8.2 集成测试

网络相关测试默认不进常规 CI，可手动运行：

```text
uv run trading-agent sentiment --tickers sample --json
```

验证：

- yfinance 能拉取样本 ticker。
- 输出日期是最近可用交易日。
- 缺失 ticker 不导致整体失败。
- 有效样本数低于阈值时输出 warning。
- yfinance 返回 MultiIndex 或单层列时都能标准化为统一长表。
- yfinance `end` 日期按排他语义处理，避免漏取或多取最后一天。

### 8.3 回测验证

初版验证目标：

```text
1. RecoveryCandidate 后 1-5 日 SPY / QQQ / IWM 收益分布。
2. RecoveryCandidate 后 Bitget stock 等权收益分布。
3. RISK_OFF 状态下新开仓候选的次日最大回撤。
4. Top200 强但 Top500 弱时，高 beta Bitget 票表现是否更差。
5. Fixed 3% 阈值与波动率标准化阈值的差异。
```

验证方法要求：

```text
1. 使用 walk-forward：
   例如 12 个月训练、3 个月验证，向前滚动。

2. 参数只在训练段调：
   验证段只能评估，不能看结果后再改同一段参数。

3. 保留最后一段 untouched holdout：
   文档化参数冻结日期，再跑最终样本外评估。

4. 报告所有状态：
   不能只挑 RecoveryCandidate 表现好的时期。

5. 对照基准：
   至少对照 buy-and-hold SPY / QQQ、随机日期、仅 MA20 修复、仅攻击波/回头波。
```

## 9. 开发阶段

### Phase 0: 数据源与研究护栏

目标：

- 明确 ticker master 来源和过滤规则。
- 明确 yfinance 使用边界。
- 明确回测验证协议，避免边实现边过拟合。

任务：

```text
1. 新增 ticker master 生成说明。
2. 固定第一版 SentimentParams 默认值。
3. 在文档中记录训练/验证/holdout 划分规则。
4. 给回测报告增加 hypothetical/backtest 免责声明。
```

验收：

```text
开发者能只看文档复现股票池生成、参数设置和验证流程。
```

### Phase 1: 公式与状态机

目标：

- 新增 `sentiment.py`。
- 完成纯函数。
- 完成无网络单元测试。

任务：

```text
1. 定义 SentimentParams。
2. 实现 compute_bar_factors。
3. 实现 aggregate_daily_sentiment。
4. 实现 MA20、新高新低、广度指标。
5. 实现 rolling percentile、EMA slope。
6. 实现 classify_sentiment_state。
7. 新增 tests/test_sentiment.py。
```

验收：

```text
uv run pytest tests/test_sentiment.py -q
uv run pytest -q
```

### Phase 2: yfinance 数据接入

目标：

- 支持从 ticker 列表拉取 yfinance OHLCV。
- 支持静态参考池文件。
- 支持 Top100/Top200/Top500 参考池选择。

任务：

```text
1. 实现 fetch_yfinance_ohlcv。
2. 实现 load_us_equity_master。
3. 实现 select_reference_universe。
4. 增加数据清洗和缺失样本 warning。
5. 增加简单缓存，避免重复请求。
```

验收：

```text
可以用 50-100 个样本 ticker 生成最近 120 日情绪历史。
当天股票池选择不使用当天成交额。
```

### Phase 3: CLI 与报告

目标：

- 新增 `trading-agent sentiment`。
- 输出简表和 JSON。
- 读取 Bitget 交易池数量，并给出仓位环境建议。

任务：

```text
1. 在 cli.py 接入 sentiment 命令。
2. 实现 build_market_sentiment_report。
3. 实现简表格式化。
4. 实现 --json、--date、--top、--compare、--tickers 参数。
5. 文档补充 CLI 使用示例。
```

验收：

```text
uv run trading-agent sentiment --json
uv run trading-agent sentiment --top 200 --compare 100,500
```

### Phase 4: 回测与参数校准

目标：

- 判断指标是否真的能捕捉冰点回暖。
- 校准阈值和状态机。

任务：

```text
1. 生成至少 1-2 年日线情绪历史。
2. 统计不同状态下 SPY / QQQ / IWM 后续收益和回撤。
3. 统计不同状态下 Bitget stock 交易池后续收益和回撤。
4. 比较 Top100/Top200/Top500。
5. 比较固定 3% 与波动率标准化版本。
```

验收：

```text
输出一份 reports/sentiment_backtest_YYYYMMDD.html 或 .md。
明确保留、删除或调整哪些指标。
```

## 10. 风险与坑

```text
1. 未来函数：
   不能用当天成交额选当天股票池。

2. yfinance 稳定性：
   数据可能缺失、超时或字段格式变化，网络获取不能进入核心单元测试。

3. ticker master 来源：
   yfinance 不适合单独发现全市场股票列表，需要单独维护 universe。

4. OHLC 调整口径：
   必须统一 adjusted 或 raw，不混用。

5. 固定 3% 阈值偏差：
   高波动股更容易触发，后续必须比较波动率标准化版本。

6. 大票护盘误判：
   Top200 回暖不代表 Top500 回暖，需要宽窄对照。

7. 空头回补误判：
   攻击波变多但 FailedAttackRatio 也高，不应直接判断 RISK_ON。

8. 事件日扰动：
   CPI、FOMC、财报密集日可能造成单日异常，趋势层要看 3 日平滑和分位。

9. Bitget 交易池偏差：
   Bitget 股票池只用于交易映射，不参与参考情绪统计。

10. 幸存者偏差：
    当前 ticker master 回测历史会漏掉退市和曾经活跃但现在不存在的股票。

11. 参数过拟合：
    多次调整阈值直到历史效果好，会高估未来效果。

12. 数据供应商限制：
    yfinance 是研究便利工具，使用前需确认 Yahoo 数据使用条款和稳定性要求。
```

## 11. 第一版成功标准

第一版完成后，应满足：

```text
1. 不依赖网络的公式和状态机测试完整通过。
2. 能用 yfinance ticker 列表生成 Top200 情绪报告。
3. 能输出当前状态：RISK_OFF / COLD / RECOVERY_CANDIDATE / RISK_ON / DIVERGENCE。
4. 能同时给出 Top100 / Top200 / Top500 对比。
5. 能说明 Bitget 交易池当前应正常、谨慎还是收缩开仓。
6. 能生成历史序列，为后续回测和阈值校准做准备。
```

## 12. 推荐立即开工顺序

```text
1. 建 `src/trading_agent/sentiment.py`。
2. 建 `tests/test_sentiment.py`。
3. 先写 `compute_bar_factors` 和测试。
4. 再写聚合指标和测试。
5. 再写状态机和测试。
6. 最后接 yfinance 和 CLI。
```

## 13. 参考依据

- [yfinance documentation](https://ranaroussi.github.io/yfinance/)：确认 yfinance 用途、法律声明和个人研究属性。
- [yfinance.download API](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html)：确认 `auto_adjust`、`end` 排他语义、MultiIndex 和批量下载参数。
- [Nasdaq Trader Symbol Directory Definitions](https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs)：用于 ticker master 字段和更新机制。
- [scikit-learn TimeSeriesSplit](https://sklearn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)：时间序列验证不能随机打乱。
- [The Probability of Backtest Overfitting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253)：回测过拟合风险和样本外验证必要性。
- [Investor.gov Performance Claims](https://www.investor.gov/index.php/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-47)：回测表现属于假设表现，不能等同实际表现。
