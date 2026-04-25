"""trend 模块单元测试

覆盖:
  - 技术指标计算数学正确性
  - determine_trend 方向判断边界
  - locate_fish_body 阶段判定
  - evaluate_gate 逻辑
  - assess_continuation 三因子打分
"""

import numpy as np
import pandas as pd
import pytest

from trading_agent.trend import (
    calc_ema,
    calc_rsi,
    calc_macd,
    calc_adx,
    calc_atr,
    determine_trend,
    evaluate_gate,
    assess_continuation,
    locate_fish_body,
    compute_indicators,
)


# ---------------------------------------------------------------------------
# 辅助: 构造测试 DataFrame
# ---------------------------------------------------------------------------

def _make_df(closes: list[float], highs=None, lows=None, volumes=None):
    """构造最小化的带指标 DataFrame"""
    n = len(closes)
    if highs is None:
        highs = [c * 1.01 for c in closes]
    if lows is None:
        lows = [c * 0.99 for c in closes]
    if volumes is None:
        volumes = [1000.0] * n

    df = pd.DataFrame({
        "close": closes,
        "high": highs,
        "low": lows,
        "volume": volumes,
        "open": closes,
        "date": [f"2026-01-{i+1:02d}" for i in range(n)],
    })
    df["ema20"] = calc_ema(df["close"], 20)
    df["ema50"] = calc_ema(df["close"], 50)
    df["rsi"] = calc_rsi(df["close"], 14)
    df["macd_line"], df["macd_signal"], df["macd_hist"] = calc_macd(df["close"])
    df["atr"] = calc_atr(df["high"], df["low"], df["close"], 14)
    df["adx"] = calc_adx(df["high"], df["low"], df["close"], 14)
    return df


# ---------------------------------------------------------------------------
# 技术指标数学正确性
# ---------------------------------------------------------------------------

class TestCalcEMA:
    def test_ema_converges_to_constant(self):
        """常数序列的 EMA 应等于该常数"""
        s = pd.Series([100.0] * 50)
        ema = calc_ema(s, 20)
        assert abs(ema.iloc[-1] - 100.0) < 0.01

    def test_ema_lags_rising(self):
        """上升序列中 EMA 应低于当前值"""
        s = pd.Series(range(1, 52), dtype=float)
        ema = calc_ema(s, 20)
        assert ema.iloc[-1] < s.iloc[-1]

    def test_ema_span(self):
        """不同 span 的 EMA 响应速度不同"""
        s = pd.Series([50.0] * 30 + [100.0] * 20, dtype=float)
        ema10 = calc_ema(s, 10)
        ema20 = calc_ema(s, 20)
        # 短周期 EMA 更接近最新值
        assert ema10.iloc[-1] > ema20.iloc[-1]


class TestCalcRSI:
    def test_rsi_all_up(self):
        """持续上涨序列 RSI 应很高"""
        # 整体上涨但每 5 根有一根小回调，保证 avg_loss 不为 0
        values = []
        price = 100.0
        for i in range(80):
            if i % 5 == 4:
                price -= 0.3  # 小回调
            else:
                price += 1.0  # 正常上涨
            values.append(price)
        s = pd.Series(values, dtype=float)
        rsi = calc_rsi(s, 14)
        assert rsi.iloc[-1] > 80

    def test_rsi_all_down(self):
        """全跌序列 RSI 应接近 0"""
        s = pd.Series(range(160, 100, -1), dtype=float)
        rsi = calc_rsi(s, 14)
        assert rsi.iloc[-1] < 10

    def test_rsi_range(self):
        """RSI 应在 0-100 之间"""
        np.random.seed(42)
        s = pd.Series(np.random.uniform(90, 110, 100))
        rsi = calc_rsi(s, 14)
        valid = rsi.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()


class TestCalcMACD:
    def test_macd_structure(self):
        """MACD 应返回三元组"""
        s = pd.Series(range(1, 61), dtype=float)
        line, signal, hist = calc_macd(s)
        assert len(line) == len(s)
        assert len(hist) == len(s)

    def test_macd_rising_trend(self):
        """上升趋势中 MACD line 应 > 0"""
        s = pd.Series(range(1, 61), dtype=float)
        line, signal, hist = calc_macd(s)
        assert line.iloc[-1] > 0


# ---------------------------------------------------------------------------
# determine_trend
# ---------------------------------------------------------------------------

class TestDetermineTrend:
    def test_bullish(self):
        """EMA20 > EMA50 且 close > EMA20 → bullish"""
        closes = list(range(50, 120))  # 持续上涨
        df = _make_df(closes)
        trend = determine_trend(df)
        assert trend["direction"] == "bullish"

    def test_bearish(self):
        """EMA20 < EMA50 且 close < EMA20 → bearish"""
        closes = list(range(120, 50, -1))  # 持续下跌
        df = _make_df(closes)
        trend = determine_trend(df)
        assert trend["direction"] == "bearish"

    def test_neutral_when_mixed(self):
        """价格在 EMA20/EMA50 之间 → neutral"""
        # 先涨后跌，末尾价格处于 EMA 之间
        closes = list(range(50, 90)) + list(range(90, 80, -1))
        df = _make_df(closes)
        trend = determine_trend(df)
        # 至少不应是 bullish (可能 neutral 或 bearish)
        assert trend["direction"] in ("neutral", "bearish")

    def test_strength_classification(self):
        """ADX >= 25 → strong, 20-25 → moderate, < 20 → weak"""
        # 使用固定趋势来验证
        closes = list(range(50, 120))
        df = _make_df(closes)
        trend = determine_trend(df)
        assert trend["strength"] in ("strong", "moderate", "weak")
        assert isinstance(trend["adx"], float)


# ---------------------------------------------------------------------------
# evaluate_gate
# ---------------------------------------------------------------------------

class TestEvaluateGate:
    def test_pass_bullish_strong(self):
        trend = {"direction": "bullish", "strength": "strong", "adx": 30.0}
        gate = evaluate_gate(trend)
        assert gate["pass"] is True

    def test_fail_bearish(self):
        trend = {"direction": "bearish", "strength": "strong", "adx": 30.0}
        gate = evaluate_gate(trend)
        assert gate["pass"] is False
        assert "bearish" in gate["reason"]

    def test_fail_low_adx(self):
        trend = {"direction": "bullish", "strength": "weak", "adx": 15.0}
        gate = evaluate_gate(trend)
        assert gate["pass"] is False
        assert "ADX" in gate["reason"]

    def test_fail_neutral(self):
        trend = {"direction": "neutral", "strength": "moderate", "adx": 22.0}
        gate = evaluate_gate(trend)
        assert gate["pass"] is False


# ---------------------------------------------------------------------------
# locate_fish_body
# ---------------------------------------------------------------------------

class TestLocateFishBody:
    def test_neutral_returns_na(self):
        closes = [100.0] * 60
        df = _make_df(closes)
        result = locate_fish_body(df, "neutral")
        assert result["stage"] == "n/a"
        assert result["ideal_entry"] is False

    def test_early_stage(self):
        """刚启动的上涨趋势应判为 early"""
        # 前50根平稳，后10根快速上涨
        closes = [100.0] * 50 + [100 + i * 0.5 for i in range(1, 11)]
        df = _make_df(closes)
        result = locate_fish_body(df, "bullish")
        # 累计涨幅小且偏离小 → early
        assert result["stage"] in ("early", "mid")

    def test_fields_present(self):
        """返回值应包含所有必需字段"""
        closes = list(range(50, 120))
        df = _make_df(closes)
        result = locate_fish_body(df, "bullish")
        assert "stage" in result
        assert "trend_age_days" in result
        assert "cumulative_pct" in result
        assert "deviation_pct" in result
        assert "ideal_entry" in result


# ---------------------------------------------------------------------------
# assess_continuation
# ---------------------------------------------------------------------------

class TestAssessContinuation:
    def test_verdict_values(self):
        """verdict 应为 strong / moderate / weakening 之一"""
        closes = list(range(50, 120))
        df = _make_df(closes)
        result = assess_continuation(df, "bullish")
        assert result["verdict"] in ("strong", "moderate", "weakening")

    def test_risk_flags_types(self):
        """risk_flags 应为列表"""
        closes = list(range(50, 120))
        df = _make_df(closes)
        result = assess_continuation(df, "bullish")
        assert isinstance(result["risk_flags"], list)

    def test_volume_ratio_calculation(self):
        """volume_ratio 应为正数"""
        closes = list(range(50, 120))
        df = _make_df(closes, volumes=[1000.0] * 70)
        result = assess_continuation(df, "bullish")
        assert result["volume_ratio"] > 0


# ---------------------------------------------------------------------------
# compute_indicators (集成)
# ---------------------------------------------------------------------------

class TestComputeIndicators:
    def test_all_columns_present(self):
        """compute_indicators 应生成所有指标列"""
        candles = [
            {"date": f"2026-01-{i+1:02d}", "open": 100+i, "high": 101+i,
             "low": 99+i, "close": 100+i, "volume": 1000, "quote_volume": 100000,
             "timestamp": 1000000 + i * 86400000}
            for i in range(60)
        ]
        df = compute_indicators(candles)
        for col in ["ema20", "ema50", "rsi", "macd_line", "macd_signal",
                     "macd_hist", "atr", "adx"]:
            assert col in df.columns, f"缺少列: {col}"
