## 波段分析报告输出模板 (基本面 + 技术面双驱动)

分析报告必须严格按以下结构输出，每个板块引用具体数据依据。

> **策略边界**: 本模板默认只输出做多波段建议；`bearish` 趋势用于回避/观察，不主动输出做空建议。

---

### 完整模板 (基本面通过 + Gate 通过)

```
## {TICKER} 波段分析报告 | {DATE}

**叙事**: {thesis 中文} ({score}/10) | **趋势**: {方向} | **鱼身**: {stage 中文} | **Gate**: PASS

---

### 📖 基本面叙事: {thesis 中文} ({score}/10)

- **业绩**: 上季 EPS {eps_actual} (预期 {eps_estimate}, 超预期 {eps_surprise_pct}%)
- **行业**: {sector} / {industry}, ETF {etf} 20d {change_20d}% ({trend 中文})
- **评级**: {rating} (均值 {rating_score}), 目标价 ${target_mean} ({upside_pct}% 空间)
- **下次财报**: {date} ({days_until} 天后, {in_window ? "⚠️ 窗口内" : "窗口外"})
- **财报催化剂**: {earnings_catalyst ? "✅ 是" : "否"} (优先使用 narrative.earnings_catalyst; 字段缺失时用 in_window && score>=6 fallback)
- **驱动**: {drivers}
- **隐忧**: {concerns}

### 📊 趋势 + 鱼身定位: {方向} ({stage 中文})

- **EMA 排列**: EMA20={ema20} {'>' if bullish else '<'} EMA50={ema50}
- **ADX**: {adx} ({strength 中文})
- **趋势启动**: {trend_age_days} 天前
- **累计涨跌**: {cumulative_pct}%
- **当前偏离 EMA20**: {deviation_pct}%
- **理想介入信号**: {ideal_entry ? "✅ 是" : "❌ 否"}

### ⚡ 延续动力: {verdict 中文}

- **动能**: MACD {momentum 中文} (histogram={macd_hist})
- **趋势强化**: ADX {上升/下降}
- **量能**: RVol={volume_ratio}x ({量级判断})
- **风险标记**: {risk_flags 中文 / "无"}

### 🎯 共振分析与仓位决策

#### 入场决定: {做 / 不做}

- 基本面: {thesis 中文} ({score}/10)
- 技术 Gate: {PASS / FAIL}
- **入场依据**: {1 句话说明}

#### 仓位倍数计算

| 维度 | 取值 | 倍数贡献 |
|------|------|---------|
| 鱼身阶段 | {stage 中文} | 基础 {X}× |
| 动力 | {verdict 中文} | {维持/调整} |
| ideal_entry | {true/false} | {如适用} |
| 叙事折扣 | {若 thesis=moderate: 矩阵基础倍数 ×0.5, 下限 0.3×; strong 则无折扣} | {×1 / ×0.5} |
| 财报因子 | {earnings_catalyst=true 不因财报打折且不自动升档; 中性叙事财报窗口 ×0.7; 弱叙事财报窗口 ×0.3 或回避} | {如适用} |
| 调整因子 | {若有: RSI 超买+鱼尾 / 已超目标价; 目标价空间为负是估值过热风险, 可与 narrative 扣分共同构成双层风控} | ×{0.7} |
| **最终仓位倍数** | | **{X.XX}×** |

**最终单笔风险**: {X.XX}× × {基础 risk_pct}% = **{Y}% 账户**

#### 关键价位

- **强支撑**: ${ema20} (EMA20) / ${ema50} (EMA50)
- **弱支撑**: ${stop} ({atr_multiple} ATR 止损位)
- **第一阻力**: ${recent_high}
- **中线目标**: ${analyst_target} (分析师均值)
- **长线目标**: ${analyst_high}

### 🛡️ 风控建议

- **入场**: ${entry} | **止损**: ${stop} ({atr_multiple} ATR, 偏离 {stop_pct}%)
- **阶段化风控**: {鱼头: 1.8-2.0 ATR/EMA50; 鱼身: 1.5 ATR/EMA20; 鱼尾: 1.0-1.5 ATR/前2日低点}
- **目标**:
  - 第一目标: ${analyst_target} (1-2 周可期, 盈亏比 {ratio_1}:1)
  - 2R 目标: ${target_2r} (3-4 周, 盈亏比 2:1)
  - 3R 目标: ${target_3r} (盈亏比 3:1)
- **仓位**: {position_size} 股 (${position_value}, 占资金 {position_pct}%)
- **最大亏损**: ${max_loss} ({risk_pct}% 账户)
- **持仓周期**: {1-2 周 / 财报催化剂持有过财报后第一根 K 线评估 / 非催化剂财报前一天评估减仓}
- **加仓条件**: {若 ideal_entry=false: 回踩 EMA20 或前高支撑不破 + 次日收阳/站回短期均线 + volume_ratio>=1.0 或动力未恶化; 加仓后总风险不超过矩阵标准倍数}
- **财报后评估**: {若 earnings_catalyst=true: 缺口不回补/守住财报前高点=兑现; 高开低走/跌破财报前低点/放量长上影=衰竭}
- **出局信号**:
  - 趋势破位 (Gate FAIL / 价格跌破 EMA20)
  - 触及止损 ${stop}
  - 触及目标价
  - 动力转弱 (verdict 变 weakening + ADX 下降)

---
⚠️ 以上为技术 + 基本面分析参考，不构成投资建议。
```

---

### 拦截分支模板

#### 分支 A: 基本面不支持 (thesis=weak 且 score<4)

```
## {TICKER} 波段分析报告 | {DATE}

**基本面拦截** — narrative.score={score}/10, thesis=weak

**原因**:
{concerns 列表}

不进入技术面分析。建议等基本面改善 (财报修复 / 行业回暖 / 评级上修) 后再观察。
```

#### 分支 B: Gate 未通过 (技术面震荡)

```
## {TICKER} 波段分析报告 | {DATE}

**技术 Gate FAIL** — {gate.reason}

虽然基本面 {thesis 中文} ({score}/10), 但当前技术面无明确趋势, 不宜介入。
建议加入 Watchlist, 等 ADX 突破 20 + 方向确认后再分析。
```

#### 分支 C: 数据缺失

```
## {TICKER} 波段分析报告 | {DATE}

**部分数据缺失**: {缺失字段列表}

**处理规则**:
- 基本面缺失 + Gate PASS + 鱼头/鱼身: 可按技术单驱动小仓位观察，建议矩阵结果 ×0.5。
- 基本面缺失 + 鱼尾: 默认不追高，加入 Watchlist。
- 技术面缺失: 不给入场建议，仅说明缺失字段。

基于可获得数据的有限分析: ...
```

---

### 中文映射表

| 字段 | 英文 | 中文 |
|------|------|------|
| thesis | strong / moderate / weak | 故事强 / 故事中性 / 故事弱 |
| direction | bullish / bearish / neutral | 多头 / 空头 / 震荡 |
| strength | strong / moderate / weak | 强 / 中等 / 弱 |
| stage | early / mid / late / n/a | 鱼头 / 鱼身 / 鱼尾 / 无趋势 |
| verdict | strong / moderate / weakening | 动力强劲 / 动力中性 / 动力减弱 |
| momentum | accelerating / decelerating / flat | 加速扩张 / 边际收缩 / 横盘震荡 |
| sector trend | bullish / mixed / bearish | 多头 / 震荡 / 空头 |
| risk_flags | rsi_overbought / rsi_oversold / volume_dry | 超买 / 超卖 / 量能枯竭 |

### 字段数据来源

| 模板字段 | 来源 |
|---------|------|
| thesis, score, earnings_catalyst, drivers, concerns | FundamentalsReport.narrative |
| eps_*, last_report_date | FundamentalsReport.earnings |
| sector, industry, etf, change_20d | FundamentalsReport.sector |
| rating, target_mean, upside_pct | FundamentalsReport.analysts |
| date, days_until, in_window | FundamentalsReport.next_earnings |
| direction, strength, adx | TrendReport.trend |
| stage, trend_age_days, cumulative_pct, deviation_pct, ideal_entry | TrendReport.fish_body |
| verdict, momentum, volume_ratio, risk_flags | TrendReport.continuation |
| ema20, ema50, recent_high, atr | TrendReport.levels |
| close, change_pct | TrendReport.price |
| entry, stop, targets, position_size | risk_calculator.py |
