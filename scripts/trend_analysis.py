"""
趋势分析脚本

基于 Bitget 日K数据计算技术指标，判断趋势方向/强度，输出结构化 TrendReport。
适配 1-2 周波段持仓周期，仅依赖 90 天日K数据。

用法:
    uv run python scripts/trend_analysis.py NVDA   # 完整趋势分析
    uv run python scripts/trend_analysis.py XAU    # 大宗商品同样支持
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# 导入数据获取
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import get_candle_data


# ---------------------------------------------------------------------------
# 技术指标计算
# ---------------------------------------------------------------------------

def calc_ema(series: pd.Series, span: int) -> pd.Series:
    """指数移动平均线"""
    return series.ewm(span=span, adjust=False).mean()


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI (Relative Strength Index)"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calc_macd(close: pd.Series,
              fast: int = 12, slow: int = 26, signal: int = 9
              ) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD (line, signal, histogram)"""
    ema_fast = calc_ema(close, fast)
    ema_slow = calc_ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series,
             period: int = 14) -> pd.Series:
    """ATR (Average True Range)"""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def calc_adx(high: pd.Series, low: pd.Series, close: pd.Series,
             period: int = 14) -> pd.Series:
    """ADX (Average Directional Index)"""
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    # +DM / -DM
    plus_dm = (high - prev_high).where((high - prev_high) > (prev_low - low), 0.0)
    plus_dm = plus_dm.where(plus_dm > 0, 0.0)
    minus_dm = (prev_low - low).where((prev_low - low) > (high - prev_high), 0.0)
    minus_dm = minus_dm.where(minus_dm > 0, 0.0)

    # True Range
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    # 平滑 (Wilder's smoothing = EMA with alpha=1/period)
    alpha = 1 / period
    atr = tr.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=alpha, min_periods=period, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=alpha, min_periods=period, adjust=False).mean() / atr

    # DX -> ADX
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    return adx


# ---------------------------------------------------------------------------
# 趋势判断
# ---------------------------------------------------------------------------

def determine_trend(df: pd.DataFrame) -> dict:
    """判断趋势方向与强度

    逻辑: EMA20/EMA50 排列 + 价格位置 → 方向; ADX → 强度
    """
    close = float(df["close"].iloc[-1])
    ema20 = float(df["ema20"].iloc[-1])
    ema50 = float(df["ema50"].iloc[-1])
    adx = float(df["adx"].iloc[-1]) if not np.isnan(df["adx"].iloc[-1]) else 0.0

    # --- 方向: 价格 + EMA 排列一致才确认 ---
    if ema20 > ema50 and close > ema20:
        direction = "bullish"
    elif ema20 < ema50 and close < ema20:
        direction = "bearish"
    else:
        direction = "neutral"

    # --- 强度: ADX ---
    if adx >= 25:
        strength = "strong"
    elif adx >= 20:
        strength = "moderate"
    else:
        strength = "weak"

    return {
        "direction": direction,
        "strength": strength,
        "adx": round(float(adx), 2),
    }


# ---------------------------------------------------------------------------
# Gate 判断
# ---------------------------------------------------------------------------

def evaluate_gate(trend: dict) -> dict:
    """Gate: ADX >= 20 且 direction == bullish (系统仅做多)"""
    adx = trend["adx"]
    direction = trend["direction"]
    passed = bool(adx >= 20 and direction == "bullish")

    if passed:
        reason = f"ADX={adx} >= 20, direction={direction}"
    else:
        reasons = []
        if adx < 20:
            reasons.append(f"ADX={adx} < 20")
        if direction == "neutral":
            reasons.append("direction=neutral")
        if direction == "bearish":
            reasons.append("direction=bearish (仅做多)")
        reason = ", ".join(reasons)

    return {"pass": passed, "reason": reason}


# ---------------------------------------------------------------------------
# 延续性评估
# ---------------------------------------------------------------------------

def assess_continuation(df: pd.DataFrame, trend_direction: str) -> dict:
    """趋势延续性评估 — 三因子打分

    因子 1: 动能方向 (MACD histogram 带符号比较，结合趋势方向)
    因子 2: 趋势强化 (ADX 是否上升)
    因子 3: 量能确认 (相对成交量)
    """
    _safe = lambda v: 0.0 if np.isnan(v) else float(v)

    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else latest

    macd_hist = _safe(latest["macd_hist"])
    prev_hist = _safe(prev["macd_hist"])
    adx = _safe(latest["adx"])
    prev_adx = _safe(df["adx"].iloc[-4]) if len(df) >= 4 else adx
    rsi = _safe(latest["rsi"])

    vol_sma20 = float(df["volume"].rolling(20).mean().iloc[-1] or 0)
    volume_ratio = round(float(latest["volume"]) / vol_sma20, 2) if vol_sma20 > 0 else 0.0

    # --- 因子 1: 动能方向 (带符号比较) ---
    if trend_direction == "bullish":
        momentum = "accelerating" if macd_hist > prev_hist else "decelerating"
    elif trend_direction == "bearish":
        momentum = "accelerating" if macd_hist < prev_hist else "decelerating"
    else:
        momentum = "flat"

    # --- 因子 2: ADX 趋势 ---
    adx_rising = bool(adx > prev_adx + 0.5)

    # --- 因子 3: 量能确认 ---
    volume_confirms = bool(volume_ratio >= 1.0)

    # --- 风险标记 (仅极端值) ---
    risk_flags = []
    if rsi > 70:
        risk_flags.append("rsi_overbought")
    if rsi < 30:
        risk_flags.append("rsi_oversold")
    if volume_ratio < 0.6:
        risk_flags.append("volume_dry")

    # --- 延续性结论 ---
    score = (1 if momentum == "accelerating" else -1) \
          + (1 if adx_rising else 0) \
          + (1 if volume_confirms else -1)

    if score >= 2:
        verdict = "strong"
    elif score >= 0:
        verdict = "moderate"
    else:
        verdict = "weakening"

    return {
        "verdict": verdict,
        "momentum": momentum,
        "adx_rising": adx_rising,
        "volume_confirms": volume_confirms,
        "volume_ratio": volume_ratio,
        "risk_flags": risk_flags,
    }


# ---------------------------------------------------------------------------
# 鱼身定位 (Stage 1.5: 判断当前处于趋势的哪个阶段)
# ---------------------------------------------------------------------------

def locate_fish_body(df: pd.DataFrame, direction: str) -> dict:
    """判断当前趋势所处阶段: 鱼头 / 鱼身 / 鱼尾

    判定要素:
      1. 趋势启动时长: 最近一次 EMA20 穿越 EMA50 距今多少根 K 线
      2. 累计涨跌幅: 从趋势启动点到当前的价格变化
      3. 偏离度: 当前价距 EMA20 的偏离 (越远越接近末段)

    阶段定义 (多头为例, 空头镜像):
      - 鱼头 (early): 启动 < 7 天 OR (累计 < 8% AND 偏离 < 5%)
      - 鱼身 (mid):   7-30 天, 累计 8-25%, 偏离 3-12%
      - 鱼尾 (late):  > 30 天 OR 累计 > 25% OR 偏离 > 12%

    适合 1-2 周波段持仓的最佳介入区: 鱼头末段 + 鱼身初段
    """
    if direction not in ("bullish", "bearish"):
        return {
            "stage": "n/a",
            "trend_age_days": None,
            "cumulative_pct": None,
            "deviation_pct": None,
            "ideal_entry": False,
        }

    close = float(df["close"].iloc[-1])
    ema20 = float(df["ema20"].iloc[-1])

    # --- 1. 找趋势启动点 (最近一次 EMA20 穿越 EMA50) ---
    # 遍历从最近往前找最后一次 cross
    ema20_series = df["ema20"]
    ema50_series = df["ema50"]
    diff = ema20_series - ema50_series

    trend_age = None
    start_idx = None
    if direction == "bullish":
        # 找最近的 diff 由 < 0 转为 > 0
        for i in range(len(diff) - 1, 0, -1):
            if pd.isna(diff.iloc[i]) or pd.isna(diff.iloc[i - 1]):
                continue
            if diff.iloc[i] > 0 and diff.iloc[i - 1] <= 0:
                start_idx = i
                break
    else:  # bearish
        for i in range(len(diff) - 1, 0, -1):
            if pd.isna(diff.iloc[i]) or pd.isna(diff.iloc[i - 1]):
                continue
            if diff.iloc[i] < 0 and diff.iloc[i - 1] >= 0:
                start_idx = i
                break

    cumulative_pct = None
    if start_idx is not None:
        trend_age = len(df) - 1 - start_idx
        start_close = float(df["close"].iloc[start_idx])
        if start_close > 0:
            cumulative_pct = round((close - start_close) / start_close * 100, 2)
    else:
        # 整个数据区间都是同一方向 → 趋势已超过数据回看窗口
        trend_age = len(df)
        # 累计变化用最早的可用数据计算
        first_valid = df["close"].iloc[0]
        if first_valid > 0:
            cumulative_pct = round((close - float(first_valid)) / float(first_valid) * 100, 2)

    # --- 2. 偏离度 ---
    deviation_pct = round((close - ema20) / ema20 * 100, 2) if ema20 > 0 else 0.0
    abs_dev = abs(deviation_pct)
    abs_cum = abs(cumulative_pct) if cumulative_pct is not None else 0

    # --- 3. 阶段判定 ---
    # 鱼尾条件 (任一触发)
    is_late = (trend_age is not None and trend_age > 30) \
              or abs_cum > 25 \
              or abs_dev > 12

    # 鱼头条件: 启动早 + 涨幅小 + 偏离小
    is_early = (trend_age is not None and trend_age < 7) \
               or (abs_cum < 8 and abs_dev < 5)

    if is_late:
        stage = "late"  # 鱼尾
    elif is_early:
        stage = "early"  # 鱼头
    else:
        stage = "mid"  # 鱼身

    # 理想介入区: 鱼头末段 (启动 5-10 天 + 偏离 < 6%) 或鱼身初段 (累计 < 18%)
    ideal_entry = (
        stage in ("early", "mid")
        and abs_dev < 6
        and abs_cum < 18
        and (trend_age is None or trend_age >= 3)  # 至少站稳 3 天
    )

    return {
        "stage": stage,
        "trend_age_days": trend_age,
        "cumulative_pct": cumulative_pct,
        "deviation_pct": deviation_pct,
        "ideal_entry": ideal_entry,
    }


# ---------------------------------------------------------------------------
# 关键价位
# ---------------------------------------------------------------------------

def find_levels(df: pd.DataFrame) -> dict:
    """计算关键支撑/阻力价位"""
    latest = df.iloc[-1]
    recent_20 = df.tail(20)

    close = float(latest["close"])
    atr = float(latest["atr"]) if not np.isnan(latest["atr"]) else 0.0

    return {
        "ema20": round(float(latest["ema20"]), 2),
        "ema50": round(float(latest["ema50"]), 2),
        "recent_high": round(float(recent_20["high"].max()), 2),
        "recent_low": round(float(recent_20["low"].min()), 2),
        "atr": round(atr, 2),
        "atr_pct": round(atr / close * 100, 2) if close > 0 else 0.0,
    }


# ---------------------------------------------------------------------------
# 报告组装
# ---------------------------------------------------------------------------

def compute_indicators(candles: list[dict]) -> pd.DataFrame:
    """将 K 线数据转为 DataFrame 并计算全部技术指标"""
    df = pd.DataFrame(candles)

    # EMA
    df["ema20"] = calc_ema(df["close"], 20)
    df["ema50"] = calc_ema(df["close"], 50)

    # RSI
    df["rsi"] = calc_rsi(df["close"], 14)

    # MACD
    df["macd_line"], df["macd_signal"], df["macd_hist"] = calc_macd(df["close"])

    # ATR
    df["atr"] = calc_atr(df["high"], df["low"], df["close"], 14)

    # ADX
    df["adx"] = calc_adx(df["high"], df["low"], df["close"], 14)

    return df


def build_trend_report(ticker: str, days: int = 90) -> dict:
    """完整趋势分析，供外部脚本调用

    Args:
        ticker: 品种代码 (如 NVDA, AAPL, XAU)
        days: 获取天数 (默认 90)

    Returns:
        完整 TrendReport 字典

    Raises:
        ValueError: ticker 不在 Bitget 品种列表中
    """
    # 获取数据
    data_report = get_candle_data(ticker, days=days)
    candles = data_report["candles"]

    if len(candles) < 50:
        raise ValueError(
            f"数据不足: {ticker} 仅获取到 {len(candles)} 根 K 线, "
            f"技术指标至少需要 50 根 (EMA50/ADX/MACD 依赖足够的历史数据)。"
        )

    # 计算指标
    df = compute_indicators(candles)

    _safe = lambda v: 0.0 if np.isnan(v) else float(v)
    latest = df.iloc[-1]
    prev_close = float(df["close"].iloc[-2]) if len(df) >= 2 else float(latest["close"])
    close = float(latest["close"])
    change_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close else 0.0

    # 因果链: 趋势 → 鱼身定位 → 延续性 → 价位 → Gate
    trend = determine_trend(df)
    fish_body = locate_fish_body(df, trend["direction"])
    continuation = assess_continuation(df, trend["direction"])
    levels = find_levels(df)
    gate = evaluate_gate(trend)

    return {
        "status": "success",
        "ticker": ticker,
        "symbol": data_report["symbol"],
        "group": data_report["group"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_points": data_report["data_points"],
        "price": {
            "close": round(close, 2),
            "change_pct": change_pct,
        },
        "trend": trend,
        "fish_body": fish_body,
        "continuation": continuation,
        "levels": levels,
        "gate": gate,
        "raw": {
            "rsi": round(_safe(latest["rsi"]), 2),
            "macd_hist": round(_safe(latest["macd_hist"]), 4),
            "volume_ratio": continuation["volume_ratio"],
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Bitget RWA 品种趋势分析"
    )
    parser.add_argument("ticker", help="品种代码 (如 NVDA, AAPL, XAU)")
    parser.add_argument("--days", type=int, default=90,
                        help="数据获取天数 (默认: 90)")
    args = parser.parse_args()

    ticker = args.ticker.upper()

    try:
        report = build_trend_report(ticker, days=args.days)
    except ValueError as e:
        print(json.dumps({"status": "error", "ticker": ticker, "message": str(e)},
                         ensure_ascii=False))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"status": "error", "ticker": ticker,
                          "message": f"分析失败: {e}"},
                         ensure_ascii=False))
        sys.exit(1)

    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
