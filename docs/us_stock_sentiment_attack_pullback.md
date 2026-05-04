# 美股情绪指标：攻击波与回头波因子设计草案

## 目标

构建一个面向美股活跃个股的情绪温度计，用来观察市场中“有效上攻”“冲高失败”和“主动回落”的比例。

初版重点不是预测单个股票，而是回答三个问题：

- 今天活跃个股中，有多少是真正攻上去并守住的？
- 有多少股票虽然冲高，但收盘或当前价明显回落？
- 当前市场是强势扩散、冲高分歧、主动退潮，还是低波动冷清？

## 价格记号

对股票 `i` 在交易日 `t`：

```text
O = 开盘价
H = 最高价
L = 最低价
C = 收盘价
P = 盘中当前价，盘中版本可用 P 替代 C
```

默认使用美股常规交易时段的复权 OHLC。若使用 24h 合约或 RWA 数据源，需要单独记录日 K 截断时间，因为非美股常规时段会改变开盘、最高、最低和收盘的含义。

## 股票池定义

默认股票池：

```text
Universe_t = t 日之前 20 个交易日平均成交额排名前 200 的美股个股
成交额 = close * volume
```

关键约束：

- 使用 `t-1` 可见的历史成交额排序，避免用当日成交额引入选择偏差。
- 优先只统计普通股；ETF、杠杆 ETF、权证、低流动性壳类标的建议排除。
- 盘中监控可以另设 `当日实时成交额前 200`，但它应被命名为“实时活跃资金情绪”，不要和回测用稳定股票池混用。

## 攻击波因子

### 原始攻击幅度

```text
AttackAmp = H / O - 1
```

该值只说明盘中最高点相对开盘价打出了多少空间，不能单独代表有效攻击。

### 攻击保持率

```text
AttackHold = (C - O) / (H - O)
```

解释：

- `AttackHold = 1`：收在最高点。
- `AttackHold = 0.5`：收在开盘价到最高价的中点。
- `AttackHold <= 0`：收盘价没有站上开盘价。

当 `H <= O` 时，该值无效，不能判定为攻击波。

### 阳线实体质量

```text
BullBodyRatio = (C - O) / (H - L)
```

该值衡量阳线实体占全天振幅的比例，用于过滤只有上影线、实体很弱的“虚攻”。

### 纯正攻击波

初版定义：

```text
PureAttack = (
    AttackAmp >= 3%
    and C > O
    and AttackHold >= 0.5
    and BullBodyRatio >= 0.30
)
```

等价理解：

- 盘中从开盘向上至少攻击 3%；
- 收成阳线；
- 收盘价站在 `O-H` 攻击路径的一半以上；
- 阳线实体不能太薄。

如果希望更贴近你说的“纯正攻击波”，核心条件是前三条；`BullBodyRatio >= 0.30` 可作为质量过滤项，后续用历史分布优化。

## 回头波因子

回头波建议拆成两类：一类衡量“冲高失败”，一类衡量“主动回落”。两者可以同时统计，因为它们表达的市场含义不同。

## 冲高失败回头

### 高点回落幅度

```text
PullbackAmp = H / C - 1
```

盘中版本：

```text
PullbackAmpLive = H_so_far / P - 1
```

### 攻击回吐率

```text
Giveback = (H - C) / (H - O)
```

解释：

- `Giveback = 0`：收在最高点。
- `Giveback = 0.5`：回吐开盘到最高价这段攻击路径的一半。
- `Giveback >= 1`：收盘价跌回开盘价以下。

当 `H <= O` 时，该值无效，因为不存在开盘后的上攻路径。

### 冲高失败回头波

初版定义：

```text
FailedAttack = (
    AttackAmp >= 3%
    and PullbackAmp >= 3%
    and Giveback >= 0.5
)
```

含义：

- 盘中确实向上攻击过；
- 从最高点到收盘或当前价回撤至少 3%；
- 至少回吐了攻击路径的一半。

这类股票可以仍然收阳，也可以收阴。它衡量的是“攻击后的承接失败”，不等同于主动杀跌。

## 纯正回头波

为了和纯正攻击波对称，纯正回头波应强调阴线实体和收盘位置。

### 下跌保持率

```text
BearHold = (O - C) / (O - L)
```

解释：

- `BearHold = 1`：收在最低点。
- `BearHold = 0.5`：收在开盘价到最低价的中点。
- `BearHold <= 0`：收盘价没有跌破开盘价。

当 `L >= O` 时，该值无效，不能判定为纯正回头波。

### 阴线实体质量

```text
BearBodyRatio = (O - C) / (H - L)
```

### 纯正回头波

初版定义：

```text
PurePullback = (
    PullbackAmp >= 3%
    and C < O
    and BearHold >= 0.5
    and BearBodyRatio >= 0.30
)
```

更严格版本可增加：

```text
BearPushAmp = O / L - 1
BearPushAmp >= 3%
```

建议初版先不强制 `BearPushAmp >= 3%`，因为回头波的核心是“从高点回落”；如果强制从开盘向下也跌满 3%，会漏掉高开冲高后大幅回落的情绪退潮票。

## 统计指标

对 `Universe_t` 中的 200 只股票，先做等权统计：

```text
RawAttackRatio = count(AttackAmp >= 3%) / N
PureAttackRatio = count(PureAttack) / N
FailedAttackRatio = count(FailedAttack) / N
PurePullbackRatio = count(PurePullback) / N

NetAttackSentiment = PureAttackRatio - PurePullbackRatio
AttackQuality = PureAttackRatio / max(RawAttackRatio, eps)
AttackFailureRate = FailedAttackRatio / max(RawAttackRatio, eps)
Divergence = PureAttackRatio + FailedAttackRatio + PurePullbackRatio
```

其中 `eps` 可取 `1 / N`，避免分母为 0。

建议同时保留成交额加权版本：

```text
DollarWeightedPureAttack =
    sum(dollar_volume_i * 1(PureAttack_i)) / sum(dollar_volume_i)

DollarWeightedPurePullback =
    sum(dollar_volume_i * 1(PurePullback_i)) / sum(dollar_volume_i)
```

成交额加权版本容易被超大成交额个股支配，建议同时计算单票权重上限，例如 `max_weight = 5%`，或者使用 `sqrt(dollar_volume)` 降低头部集中度。

## 情绪状态解释

```text
PureAttackRatio 高，FailedAttackRatio 低，PurePullbackRatio 低：
    真强，攻击有效且承接好。

RawAttackRatio 高，PureAttackRatio 低，FailedAttackRatio 高：
    假强或分歧，盘中冲高多，但守不住。

PurePullbackRatio 高，NetAttackSentiment < 0：
    主动退潮，市场风险偏好下降。

PureAttackRatio 高，PurePullbackRatio 也高：
    剧烈分歧，高波动环境，适合降低对单边延续的假设。

PureAttackRatio 低，FailedAttackRatio 低，PurePullbackRatio 低：
    情绪冷清，可能是低波动等待方向。
```

## 情绪变化趋势与冰点回暖

这个指标可以反映情绪变化趋势，但它反映的是价格行为中的风险偏好，而不是新闻、社媒或文本情绪。

单日数值只回答“今天热不热”，趋势层要回答：

```text
市场是否从没人敢追、冲高就砸、阴线扩散，
逐渐转向回头波减少、有效攻击增加、攻击质量变好？
```

### 趋势派生指标

对核心指标做平滑、斜率和历史分位：

```text
NetAttackSentiment = PureAttackRatio - PurePullbackRatio
AttackQuality = PureAttackRatio / max(RawAttackRatio, eps)
AttackFailureRate = FailedAttackRatio / max(RawAttackRatio, eps)

NetAttackEMA3 = EMA(NetAttackSentiment, 3)
PureAttackEMA3 = EMA(PureAttackRatio, 3)
PurePullbackEMA3 = EMA(PurePullbackRatio, 3)
FailureEMA3 = EMA(AttackFailureRate, 3)

NetAttackSlope3 = NetAttackEMA3 - NetAttackEMA3.shift(3)
PullbackSlope3 = PurePullbackEMA3 - PurePullbackEMA3.shift(3)
FailureSlope3 = FailureEMA3 - FailureEMA3.shift(3)

NetAttackPctRank90 = NetAttackSentiment 过去 90 日历史分位
PureAttackPctRank90 = PureAttackRatio 过去 90 日历史分位
PurePullbackPctRank90 = PurePullbackRatio 过去 90 日历史分位
FailurePctRank90 = AttackFailureRate 过去 90 日历史分位
```

平滑的目的不是让指标变漂亮，而是降低单日财报、CPI、FOMC 或个别超大票扰动。

### 冰点定义

冰点不是简单的“攻击少”，而是“有效攻击少，主动回落或冲高失败多”。初版可以定义为：

```text
ColdPoint = (
    PureAttackPctRank90 <= 20
    and (
        PurePullbackPctRank90 >= 80
        or FailurePctRank90 >= 80
        or NetAttackPctRank90 <= 20
    )
)
```

更保守版本要求指数确认：

```text
ColdPointConfirmed = (
    ColdPoint
    and (QQQ 或 SPY 处于 5 日/10 日均线下方，或近 5 日有明显回撤)
)
```

### 冰点回暖候选

从冰点回暖的关键不是第一天攻击波很多，而是退潮压力先减弱，然后攻击质量改善。

推荐候选信号：

```text
RecoveryCandidate = (
    ColdPoint 在过去 5 个交易日内出现过
    and NetAttackSlope3 > 0
    and PullbackSlope3 < 0
    and FailureSlope3 <= 0
    and PureAttackPctRank90 >= 40
)
```

含义：

- 近期确实冷过；
- 净攻击情绪开始改善；
- 主动回落占比下降；
- 冲高失败率不再恶化；
- 有效攻击已经回到历史偏中性区域。

### 回暖确认

确认信号应更严格，用来提高仓位或放大候选优先级：

```text
RecoveryConfirmed = (
    RecoveryCandidate
    and NetAttackPctRank90 >= 50
    and PureAttackPctRank90 >= 50
    and FailurePctRank90 <= 60
    and Top500 的 NetAttackSlope3 >= 0
)
```

如果再加指数价格确认：

```text
IndexConfirm = (
    QQQ 或 SPY 不再创 5 日新低
    or QQQ / SPY 收回 5 日均线
)
```

则可把 `RecoveryConfirmed and IndexConfirm` 作为更保守的回暖信号。

### 状态机

初版状态可以简化为 5 类：

```text
RISK_OFF:
    PurePullbackPctRank90 高，NetAttackPctRank90 低，且斜率继续恶化。

COLD:
    有效攻击低，回头波或失败率高，但恶化速度放缓。

RECOVERY_CANDIDATE:
    从 COLD 后，回头波下降、失败率下降、净攻击斜率转正。

RISK_ON:
    有效攻击占比回到中高分位，失败率不高，Top200 / Top500 同向改善。

DIVERGENCE:
    攻击多，失败也多，或 Top200 强而 Top500 弱。
```

状态转换建议：

```text
RISK_OFF -> COLD:
    回头波仍高，但 NetAttackSentiment 不再继续快速下降。

COLD -> RECOVERY_CANDIDATE:
    NetAttackSlope3 > 0，PullbackSlope3 < 0，FailureSlope3 <= 0。

RECOVERY_CANDIDATE -> RISK_ON:
    PureAttackPctRank90 >= 50，FailurePctRank90 <= 60，Top500 不拖后腿。

RECOVERY_CANDIDATE -> DIVERGENCE:
    PureAttackRatio 抬升，但 FailedAttackRatio 同步高企。

任意状态 -> RISK_OFF:
    PurePullbackPctRank90 >= 80 且 NetAttackSlope3 < 0。
```

### 冰点回暖的坑

- 下跌加速会伪装成冰点：只看低位会太早，必须看 `NetAttackSlope3` 和 `PullbackSlope3`。
- 空头回补会伪装成回暖：攻击波突然增加但 `FailedAttackRatio` 也高，说明承接仍不稳。
- 大票护盘会伪装成扩散：Top200 改善但 Top500 没改善，说明风险偏好没有真正扩散。
- 固定 3% 阈值偏向高波动股：必须并行观察波动率标准化版本。
- 单日事件会污染状态：财报密集日、CPI、FOMC、期权到期日建议标记，不要机械解释。
- 指标适合做环境开关，不适合单独抄底：单票仍要看趋势结构、位置、止损空间和基本面事件。

## 成交额前 200 口径评估

### 合理性

“成交额前 200 个股”适合作为初版口径，原因是：

- 流动性充足，价格形态和成交额更可交易，噪声少于小票。
- 能较好覆盖美股中机构资金和主动交易资金关注的主战场。
- 对盘中监控友好，指标变化一般来自真实资金行为，而不是冷门股偶然波动。
- 股票数量足够形成广度统计，又不会过宽到被大量低成交额股票稀释。

因此，初版可以把它定义为：

```text
美股活跃大票情绪指标
```

而不是：

```text
全市场美股情绪指标
```

### 主要问题

这个口径也有明显偏差：

- 头部集中偏差：少数超大成交额股票可能支配成交额加权结果。
- 大盘成长偏差：前 200 往往更偏向大型科技、热门成长、财报或事件驱动标的。
- 小票风险偏好缺失：无法充分反映 Russell 2000、小盘股、低价股的情绪。
- 行业结构漂移：不同阶段成交额前 200 的行业权重会变，直接比较历史数值时可能混入行业变化。
- 当日排序偏差：如果用当天成交额选前 200，强波动股票更容易被纳入，会高估情绪波动。

### 建议做法

初版建议采用“三层口径”：

```text
主指标：
    过去 20 日平均成交额前 200，等权统计。

资金强度辅助指标：
    同一股票池内做成交额加权统计，但限制单票权重。

稳健性对照指标：
    同样定义分别跑 Top100、Top500，观察结论是否稳定。
```

如果 Top200 和 Top500 方向一致，说明情绪扩散较强；如果 Top200 很强但 Top500 一般，说明主要是大票或热门票行情；如果 Top500 更弱甚至回头波更高，说明市场内部承接不足。

### 最小验证清单

上线前建议至少检查：

- 股票池每日换手率：Top200 成分变化过快会让序列不稳定。
- 行业分布：统计每个行业的攻击占比和回头占比，避免被单一行业解释掉。
- 头部权重：成交额加权版本中，前 10 只股票贡献了多少权重。
- 阈值敏感性：`3%`、`2.5%`、`1.5 * ATR20日均日内振幅` 三套定义是否给出相近状态。
- 与 SPY、QQQ、IWM 的关系：分别测试次日收益、次日最大回撤、未来 1-3 日波动率。
- 盘中与日线一致性：盘中版本在美股收盘前是否频繁反复，是否需要收盘前 30 分钟才定信号。

## 最终口径：参考池与交易池分离

更推荐的结构是把“情绪参考池”和“实际交易池”拆开：

```text
情绪参考池：
    yfinance 获取的美股高成交额前排个股，例如过去 20 日平均成交额 Top200 / Top500。

实际交易池：
    Bitget RWA 中可交易的美股个股。
```

这比直接用 Bitget 股票池统计情绪更可靠。原因是 Bitget 当前可交易股票数量较少，而且偏向热门大票、高 beta、AI/半导体、加密相关和中概 ADR；它适合作为执行池，不适合作为全局情绪参考池。

### yfinance 参考池

推荐定义：

```text
ReferenceUniverse_t =
    全部可获取美股普通股中，
    使用 t-1 可见数据计算过去 20 日平均成交额，
    排名前 200 的股票。

成交额 = adjusted close * volume
```

可同时维护三套口径：

```text
Top100:
    最活跃核心票，最贴近大资金和盘面主线。

Top200:
    默认主指标，兼顾活跃度和广度。

Top500:
    稳健性对照，用来看情绪是否扩散到更宽的股票层。
```

实现时注意：

- yfinance 适合获取 OHLCV，不一定适合单独发现“全市场股票列表”；最好先有一个可缓存的美股 ticker master，再用 yfinance 批量拉行情。
- 股票池排序必须使用 `t-1` 以前的数据，不能用当天成交额选当天股票池。
- 优先排除 ETF、杠杆 ETF、权证、优先股、低价极小票；ADR 是否纳入可以单独开关。
- 攻击波和回头波建议使用美股常规交易时段日线 OHLC，而不是 Bitget 24h K 线。
- 参考池缺失数据时，不要前向填充 OHLC；当天缺失就从分母中剔除，并记录有效样本数。

### Bitget 交易池

截至 `2026-05-04` 同步结果，Bitget RWA 共 `77` 个：

```text
stock: 57
etf: 12
commodity: 8
```

其中 `PAXG`、`XAUT` 属于黄金类资产，应归入 commodity，不进入 stock 交易池。

当前 Bitget stock 交易池：

```text
AAOI, AAPL, AMAT, AMD, AMZN, APLD, APP, ARM, ASML, AVGO,
BA, BABA, BE, BZ, CL, COHR, COIN, COP, COST, CRCL,
CRDO, CRWV, FLY, FUTU, GE, GME, GOOGL, HOOD, INTC, IONQ,
JD, KLAC, LITE, LLY, MCD, META, MP, MRVL, MSFT, MSTR,
MU, NBIS, NFLX, NVDA, OKLO, ORCL, OXY, PLTR, RDDT, RKLB,
SNDK, STXSTOCK, TSLA, TSM, UNH, WMT, XOM
```

Bitget 股票池的用途应是：

```text
1. 生成可交易候选。
2. 判断单票趋势、位置、风险和执行价格。
3. 接收参考池情绪信号，决定是否放大或收缩开仓积极性。
```

### 情绪到交易的映射

推荐让 yfinance 参考池输出环境信号，再作用到 Bitget 交易池：

```text
ReferencePureAttackRatio 高，ReferenceFailedAttackRatio 低：
    市场环境支持做多，Bitget 候选可以正常排序和开仓。

ReferenceFailedAttackRatio 高：
    外部市场冲高失败多，Bitget 候选即便强，也降低追高权重。

ReferencePurePullbackRatio 高，NetAttackSentiment < 0：
    外部市场主动退潮，Bitget 交易池降低总仓位，收紧止损。

ReferenceTop200 强，但 ReferenceTop500 弱：
    大票强、小票弱，优先 Bitget 里的 mega cap 和指数相关标的，谨慎高 beta 小票。

ReferenceTop500 也强：
    情绪扩散充分，Bitget 高 beta 候选的胜率环境更好。
```

### 优化思路

更稳健的优化方向：

- 固定阈值和波动率阈值并行：同时计算 `3%` 与 `k * 20日平均日内振幅`。
- 做宽窄对比：Top100、Top200、Top500 同时计算，判断情绪是集中还是扩散。
- 做行业/主题拆分：AI/semis、mega cap、crypto beta、中概、能源、防御消费分别统计。
- 用滚动分位数：把情绪指标转成过去 60 日或 90 日分位，少看绝对值，多看历史位置。
- 对参考池做 3 日平滑：减少单日财报、CPI、FOMC 等事件扰动。
- 对 Bitget 交易池做映射验证：测试参考池情绪对 Bitget stock 等权收益、扫描通过率、次日最大回撤和止损触发率的影响。

### 推荐使用方式

该指标初期更适合作为仓位开关，而不是单独买卖信号：

```text
ReferenceNetAttackSentiment > 历史 70 分位，且 AttackFailureRate 不高：
    允许正常开仓或提高候选优先级。

ReferenceFailedAttackRatio > 历史 80 分位：
    降低追高权重，优先等回踩或只做最强个股。

ReferencePurePullbackRatio > 历史 80 分位，且 NetAttackSentiment < 0：
    降低总仓位，收紧止损，减少新开仓。
```

不要在未回测前把它作为单独买卖信号。它的价值主要是帮助判断“外部市场环境是否支持积极交易 Bitget 里的候选标的”。

## 开发落地规格

### 模块边界

建议新增独立模块，不复用 Bitget 专用的 `data.py`：

```text
src/trading_agent/sentiment.py
    负责攻击波/回头波单票因子、聚合指标、趋势状态机和报告输出。

src/trading_agent/yfinance_data.py
    负责 yfinance OHLCV 批量拉取、缓存和数据清洗。

config/us_equity_universe.json
    可缓存的美股 ticker master，包含 ticker、名称、类型、交易所、是否 ETF/ADR 等字段。

config/sentiment_cache.json
    可选缓存，保存最近参考池和情绪结果；应加入 .gitignore。
```

先实现时也可以只做 `sentiment.py`，把 yfinance 拉取函数放在模块内，等逻辑稳定后再拆出 `yfinance_data.py`。

### 数据输入

初版输入结构：

```text
price_panel:
    MultiIndex 或长表 DataFrame
    字段: date, ticker, open, high, low, close, volume

universe_master:
    ticker, asset_type, exchange, is_etf, is_adr, active

params:
    universe_lookback_days = 20
    reference_top_n = 200
    compare_top_n = [100, 500]
    attack_threshold = 0.03
    pullback_threshold = 0.03
    body_ratio_threshold = 0.30
    hold_threshold = 0.50
    percentile_lookback_days = 90
    smooth_span = 3
```

OHLC 要保持同一调整口径：如果 yfinance 使用 `auto_adjust=True`，攻击波和回头波的 `O/H/L/C` 都使用调整后的 OHLC；不要把 raw open/high/low 和 adjusted close 混用。

### 核心函数

建议先做纯函数，便于测试：

```text
compute_bar_factors(row, params) -> dict
    输入单根日 K，输出 AttackAmp、PullbackAmp、PureAttack、FailedAttack、PurePullback 等。

compute_factor_frame(price_panel, params) -> DataFrame
    对所有 ticker/date 计算单票因子。

select_reference_universe(price_panel, as_of_date, top_n, lookback_days, master) -> list[str]
    使用 as_of_date 前一交易日可见数据选成交额前 N。

aggregate_sentiment(factor_frame, universe, date, params, weight_mode="equal") -> dict
    聚合 RawAttackRatio、PureAttackRatio、FailedAttackRatio、PurePullbackRatio 等。

compute_sentiment_history(price_panel, dates, top_n, params) -> DataFrame
    批量生成历史情绪序列。

classify_sentiment_state(sentiment_history, params) -> dict
    输出 RISK_OFF / COLD / RECOVERY_CANDIDATE / RISK_ON / DIVERGENCE。

build_market_sentiment_report(...) -> dict
    汇总参考池、Top100/Top200/Top500、状态机、风险提示和 Bitget 交易池映射。
```

### 输出结构

单日报告建议：

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
    "net_attack_sentiment": 0.03,
    "attack_quality": 0.61,
    "attack_failure_rate": 0.33
  },
  "trend": {
    "state": "RECOVERY_CANDIDATE",
    "net_attack_slope_3": 0.05,
    "pullback_slope_3": -0.04,
    "failure_slope_3": -0.02
  },
  "breadth_compare": {
    "top100_state": "RISK_ON",
    "top200_state": "RECOVERY_CANDIDATE",
    "top500_state": "COLD"
  },
  "warnings": [
    "Top200 stronger than Top500; recovery may be concentrated in large caps."
  ]
}
```

### CLI 入口

建议新增命令：

```text
uv run trading-agent sentiment
uv run trading-agent sentiment --date 2026-05-01
uv run trading-agent sentiment --top 200 --compare 100,500
uv run trading-agent sentiment --refresh-universe
uv run trading-agent sentiment --json
```

初版可以先只支持日线收盘后计算，不做盘中版本。盘中版本需要分钟级数据和交易时段处理，复杂度高一档。

### 测试优先级

先写不依赖网络的单元测试：

```text
1. 纯正攻击波：
   H/O >= 3%，C > O，AttackHold >= 0.5，BullBodyRatio >= 0.30。

2. 冲高失败：
   AttackAmp >= 3%，PullbackAmp >= 3%，Giveback >= 0.5。

3. 纯正回头波：
   PullbackAmp >= 3%，C < O，BearHold >= 0.5，BearBodyRatio >= 0.30。

4. 边界条件：
   H <= O、L >= O、H == L、O/C 为 0 或缺失时不报错且不给误判。

5. 股票池选择：
   as_of_date 当天成交额暴增的股票不能进入当天参考池，只能从下一天开始生效。

6. 状态机：
   构造 COLD -> RECOVERY_CANDIDATE -> RISK_ON 的小样本序列，确认状态转换。
```

网络和 yfinance 只放集成测试或手动验证，避免常规测试因为限流、网络或 Yahoo 返回格式波动而失败。

### 第一阶段实现顺序

```text
1. 新增 sentiment.py，完成单票因子和聚合纯函数。
2. 新增 tests/test_sentiment.py，覆盖公式、边界和状态机。
3. 增加 yfinance 批量 OHLCV 拉取，先支持手工传入 ticker 列表。
4. 增加 reference universe 选择逻辑，保证 t-1 防未来函数。
5. 增加 CLI sentiment，输出 JSON 和简表。
6. 接入 Bitget 交易池映射：只读 config/bitget_symbols.json，不参与参考池计算。
```

## 初版结论

成交额前 200 是合理的第一版，但它应该被定位为“活跃大票情绪”，不是完整的全市场情绪。实际落地时建议明确拆成 yfinance 参考池和 Bitget 交易池。

最推荐的第一版组合是：

```text
ReferenceUniverse = yfinance 美股普通股，前 20 日平均成交额 Top200
TradeUniverse = Bitget group == stock 的可交易股票

核心指标：
    PureAttackRatio
    FailedAttackRatio
    PurePullbackRatio
    NetAttackSentiment
    AttackFailureRate

辅助指标：
    成交额加权版本
    Top100 / Top500 稳健性对照
    行业分布版本
    Bitget 交易池映射验证
```

后续优化优先级：

1. 先确认 3% 阈值在历史分布中的分位位置。
2. 再比较固定阈值和 ATR 标准化阈值。
3. 最后决定是否把 Top200 升级为 Top500 或行业中性股票池。
