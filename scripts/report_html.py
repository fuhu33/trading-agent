"""
HTML 交互式分析报告生成器

基于 TrendReport + FundamentalsReport 生成带 K 线图的完整 HTML 报告。
图表使用 TradingView Lightweight Charts (CDN), 无需本地依赖。

用法:
    uv run python scripts/report_html.py INTC                # 生成并打开报告
    uv run python scripts/report_html.py INTC --no-open      # 仅生成不打开
    uv run python scripts/report_html.py INTC --with-fund    # 含基本面
    uv run python scripts/report_html.py INTC --serve        # 启动本地服务器预览
"""

import argparse
import json
import os
import sys
import webbrowser
from datetime import datetime, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import get_candle_data
from trend_analysis import compute_indicators, determine_trend, locate_fish_body, assess_continuation, find_levels, evaluate_gate

# 可选: 基本面
try:
    from fundamentals import build_fundamentals_report
    HAS_FUNDAMENTALS = True
except ImportError:
    HAS_FUNDAMENTALS = False

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "reports"

DIRECTION_ZH = {"bullish": "多头 📈", "bearish": "空头 📉", "neutral": "震荡 ➡️"}
MOMENTUM_ZH = {"accelerating": "扩张", "decelerating": "收缩", "flat": "横盘"}
STAGE_ZH = {"early": "🐟 鱼头", "mid": "🐟 鱼身", "late": "🐟 鱼尾", "n/a": "-"}
THESIS_ZH = {"strong": "强", "moderate": "中", "weak": "弱"}
VERDICT_ZH = {"strong": "强", "moderate": "中", "weakening": "弱"}


# ---------------------------------------------------------------------------
# 数据准备
# ---------------------------------------------------------------------------

def prepare_chart_data(ticker: str, days: int = 90) -> dict:
    """获取 K 线 + 计算指标, 返回图表和分析所需的全部数据"""
    data_report = get_candle_data(ticker, days=days)
    candles = data_report["candles"]

    if len(candles) < 50:
        raise ValueError(f"数据不足: {ticker} 仅 {len(candles)} 根 K 线")

    df = compute_indicators(candles)
    _safe = lambda v: 0.0 if (isinstance(v, float) and np.isnan(v)) else float(v)

    # 图表数据: K 线
    chart_candles = []
    for _, row in df.iterrows():
        chart_candles.append({
            "time": row["date"],
            "open": round(float(row["open"]), 2),
            "high": round(float(row["high"]), 2),
            "low": round(float(row["low"]), 2),
            "close": round(float(row["close"]), 2),
        })

    # 图表数据: 成交量
    chart_volume = []
    for _, row in df.iterrows():
        color = "rgba(38,166,154,0.5)" if row["close"] >= row["open"] else "rgba(239,83,80,0.5)"
        chart_volume.append({
            "time": row["date"],
            "value": round(float(row["volume"]), 2),
            "color": color,
        })

    # 图表数据: EMA
    chart_ema20 = []
    chart_ema50 = []
    for _, row in df.iterrows():
        ema20_item = {"time": row["date"]}
        ema50_item = {"time": row["date"]}
        if not np.isnan(row["ema20"]):
            ema20_item["value"] = round(float(row["ema20"]), 2)
        if not np.isnan(row["ema50"]):
            ema50_item["value"] = round(float(row["ema50"]), 2)
        chart_ema20.append(ema20_item)
        chart_ema50.append(ema50_item)

    # 图表数据: RSI
    chart_rsi = []
    for _, row in df.iterrows():
        item = {"time": row["date"]}
        if not np.isnan(row["rsi"]):
            item["value"] = round(_safe(row["rsi"]), 2)
        chart_rsi.append(item)

    # 图表数据: MACD
    chart_macd_line = []
    chart_macd_signal = []
    chart_macd_hist = []
    for _, row in df.iterrows():
        macd_line_item = {"time": row["date"]}
        macd_signal_item = {"time": row["date"]}
        macd_hist_item = {"time": row["date"]}
        if not np.isnan(row["macd_line"]):
            macd_line_item["value"] = round(_safe(row["macd_line"]), 4)
        if not np.isnan(row["macd_signal"]):
            macd_signal_item["value"] = round(_safe(row["macd_signal"]), 4)
        if not np.isnan(row["macd_hist"]):
            v = _safe(row["macd_hist"])
            macd_hist_item["value"] = round(v, 4)
            macd_hist_item["color"] = "rgba(38,166,154,0.7)" if v >= 0 else "rgba(239,83,80,0.7)"
        chart_macd_line.append(macd_line_item)
        chart_macd_signal.append(macd_signal_item)
        chart_macd_hist.append(macd_hist_item)

    # 分析数据
    latest = df.iloc[-1]
    prev_close = float(df["close"].iloc[-2]) if len(df) >= 2 else float(latest["close"])
    close = float(latest["close"])
    change_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close else 0.0

    trend = determine_trend(df)
    fish_body = locate_fish_body(df, trend["direction"])
    continuation = assess_continuation(df, trend["direction"])
    levels = find_levels(df)
    gate = evaluate_gate(trend)

    return {
        "ticker": ticker,
        "symbol": data_report["symbol"],
        "group": data_report["group"],
        "data_points": data_report["data_points"],
        "price": {"close": round(close, 2), "change_pct": change_pct},
        "trend": trend,
        "fish_body": fish_body,
        "continuation": continuation,
        "levels": levels,
        "gate": gate,
        "raw": {
            "rsi": round(_safe(latest["rsi"]), 2),
            "macd_hist": round(_safe(latest["macd_hist"]), 4),
        },
        "chart": {
            "candles": chart_candles,
            "volume": chart_volume,
            "ema20": chart_ema20,
            "ema50": chart_ema50,
            "rsi": chart_rsi,
            "macd_line": chart_macd_line,
            "macd_signal": chart_macd_signal,
            "macd_hist": chart_macd_hist,
        },
    }


# ---------------------------------------------------------------------------
# HTML 模板
# ---------------------------------------------------------------------------

def build_html(data: dict, fund: dict | None = None) -> str:
    """生成完整 HTML 报告"""
    ticker = data["ticker"]
    close = data["price"]["close"]
    change = data["price"]["change_pct"]
    trend = data["trend"]
    fish = data["fish_body"]
    cont = data["continuation"]
    levels = data["levels"]
    gate = data["gate"]

    direction_zh = DIRECTION_ZH.get(trend["direction"], trend["direction"])
    momentum_zh = MOMENTUM_ZH.get(cont["momentum"], cont["momentum"])
    stage_zh = STAGE_ZH.get(fish.get("stage", "n/a"), "-")
    verdict_zh = VERDICT_ZH.get(cont["verdict"], cont["verdict"])

    change_class = "up" if change >= 0 else "down"
    change_str = f"{change:+.2f}%"
    gate_str = "✅ PASS" if gate["pass"] else "❌ FAIL"
    gate_class = "pass" if gate["pass"] else "fail"

    risk_flags_str = ", ".join(cont["risk_flags"]) if cont["risk_flags"] else "无"

    # 基本面区块
    fund_html = ""
    if fund and fund.get("status") == "success":
        n = fund.get("narrative", {})
        e = fund.get("earnings") or {}
        ne = fund.get("next_earnings") or {}
        s = fund.get("sector") or {}
        a = fund.get("analysts") or {}

        thesis_zh = THESIS_ZH.get(n.get("thesis"), "-")
        drivers = "<br>".join(f"✅ {d}" for d in n.get("drivers", []))
        concerns = "<br>".join(f"⚠️ {c}" for c in n.get("concerns", []))

        eps_str = f"{e.get('eps_surprise_pct', 0):+.1f}%" if e.get("eps_surprise_pct") is not None else "N/A"
        sector_trend = s.get("trend", "N/A")
        rating = a.get("rating", "N/A")
        upside = f"{a.get('upside_pct', 0):+.1f}%" if a.get("upside_pct") is not None else "N/A"
        earnings_date = ne.get("date", "N/A")
        earnings_days = ne.get("days_until", "N/A")
        in_window = "⚠️ 是" if ne.get("in_window") else "否"

        fund_html = f"""
        <div class="card fund-card">
            <h3>📊 基本面叙事 (Score: {n.get('score', '-')}/10, Thesis: {thesis_zh})</h3>
            <div class="metrics-grid">
                <div class="metric">
                    <span class="metric-label">EPS 超预期</span>
                    <span class="metric-value">{eps_str}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">行业趋势</span>
                    <span class="metric-value">{sector_trend} ({s.get('etf', '-')})</span>
                </div>
                <div class="metric">
                    <span class="metric-label">分析师评级</span>
                    <span class="metric-value">{rating}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">目标价空间</span>
                    <span class="metric-value">{upside}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">下次财报</span>
                    <span class="metric-value">{earnings_date} ({earnings_days}天)</span>
                </div>
                <div class="metric">
                    <span class="metric-label">财报窗口内</span>
                    <span class="metric-value">{in_window}</span>
                </div>
            </div>
            <div class="narrative-box">
                <div class="drivers">{drivers if drivers else "无"}</div>
                <div class="concerns">{concerns if concerns else "无"}</div>
            </div>
        </div>
        """

    # 图表数据 JSON
    chart_json = json.dumps(data["chart"], ensure_ascii=False)

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{ticker} 波段分析报告</title>
<style>
  :root {{
    --bg: #0d1117;
    --card-bg: #161b22;
    --border: #30363d;
    --text: #e6edf3;
    --text-muted: #8b949e;
    --green: #26a69a;
    --red: #ef5350;
    --blue: #58a6ff;
    --yellow: #d29922;
    --purple: #bc8cff;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    line-height: 1.6;
    padding: 20px;
    max-width: 1400px;
    margin: 0 auto;
  }}
  .header {{
    display: flex;
    align-items: baseline;
    gap: 16px;
    margin-bottom: 8px;
    flex-wrap: wrap;
  }}
  .header h1 {{
    font-size: 2em;
    font-weight: 700;
  }}
  .price {{
    font-size: 1.8em;
    font-weight: 600;
  }}
  .change {{
    font-size: 1.2em;
    font-weight: 600;
    padding: 2px 10px;
    border-radius: 4px;
  }}
  .change.up {{ background: rgba(38,166,154,0.2); color: var(--green); }}
  .change.down {{ background: rgba(239,83,80,0.2); color: var(--red); }}
  .subtitle {{
    color: var(--text-muted);
    font-size: 0.85em;
    margin-bottom: 20px;
  }}
  .gate-banner {{
    padding: 12px 20px;
    border-radius: 8px;
    font-size: 1.1em;
    font-weight: 600;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 12px;
  }}
  .gate-banner.pass {{
    background: rgba(38,166,154,0.15);
    border: 1px solid var(--green);
    color: var(--green);
  }}
  .gate-banner.fail {{
    background: rgba(239,83,80,0.15);
    border: 1px solid var(--red);
    color: var(--red);
  }}
  .chart-section {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 20px;
  }}
  .chart-section h3 {{
    margin-bottom: 12px;
    color: var(--text-muted);
    font-size: 0.9em;
    font-weight: 500;
  }}
  #main-chart {{ width: 100%; height: 400px; }}
  #rsi-chart {{ width: 100%; height: 150px; margin-top: 4px; }}
  #macd-chart {{ width: 100%; height: 150px; margin-top: 4px; }}
  .cards-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 16px;
    margin-bottom: 20px;
  }}
  .card {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
  }}
  .card h3 {{
    font-size: 1em;
    margin-bottom: 14px;
    color: var(--blue);
  }}
  .metrics-grid {{
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
  }}
  .metric {{
    display: flex;
    flex-direction: column;
    gap: 2px;
  }}
  .metric-label {{
    font-size: 0.78em;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }}
  .metric-value {{
    font-size: 1.1em;
    font-weight: 600;
  }}
  .metric-value.green {{ color: var(--green); }}
  .metric-value.red {{ color: var(--red); }}
  .metric-value.yellow {{ color: var(--yellow); }}
  .tag {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.8em;
    font-weight: 600;
  }}
  .tag.bullish {{ background: rgba(38,166,154,0.2); color: var(--green); }}
  .tag.bearish {{ background: rgba(239,83,80,0.2); color: var(--red); }}
  .tag.neutral {{ background: rgba(139,148,158,0.2); color: var(--text-muted); }}
  .narrative-box {{
    margin-top: 12px;
    padding: 12px;
    background: rgba(255,255,255,0.03);
    border-radius: 8px;
    font-size: 0.9em;
    line-height: 1.8;
  }}
  .fund-card {{
    grid-column: 1 / -1;
  }}
  .levels-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9em;
  }}
  .levels-table td {{
    padding: 6px 0;
    border-bottom: 1px solid var(--border);
  }}
  .levels-table td:last-child {{
    text-align: right;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }}
  .footer {{
    color: var(--text-muted);
    font-size: 0.75em;
    text-align: center;
    margin-top: 30px;
    padding-top: 16px;
    border-top: 1px solid var(--border);
  }}
  .chart-legend {{
    display: flex;
    gap: 16px;
    margin-bottom: 8px;
    font-size: 0.8em;
    color: var(--text-muted);
  }}
  .chart-legend span::before {{
    content: '';
    display: inline-block;
    width: 12px;
    height: 3px;
    margin-right: 4px;
    vertical-align: middle;
    border-radius: 2px;
  }}
  .legend-ema20::before {{ background: var(--blue); }}
  .legend-ema50::before {{ background: var(--purple); }}
</style>
</head>
<body>

<div class="header">
  <h1>{ticker}</h1>
  <span class="price">${close}</span>
  <span class="change {change_class}">{change_str}</span>
</div>
<div class="subtitle">
  {data['symbol']} · {data['group']} · {data['data_points']}D 日K · {now_str}
</div>

<div class="gate-banner {gate_class}">
  <span style="font-size:1.4em">{"✅" if gate["pass"] else "❌"}</span>
  <span>Gate: {gate_str}</span>
  <span style="font-weight:400;color:var(--text-muted);font-size:0.85em">— {gate["reason"]}</span>
</div>

<!-- 图表 -->
<div class="chart-section">
  <div class="chart-legend">
    <span class="legend-ema20">EMA20</span>
    <span class="legend-ema50">EMA50</span>
  </div>
  <div id="main-chart"></div>
  <h3>RSI (14)</h3>
  <div id="rsi-chart"></div>
  <h3>MACD (12, 26, 9)</h3>
  <div id="macd-chart"></div>
</div>

<!-- 分析卡片 -->
<div class="cards-grid">
  <div class="card">
    <h3>📈 趋势判断</h3>
    <div class="metrics-grid">
      <div class="metric">
        <span class="metric-label">方向</span>
        <span class="metric-value"><span class="tag {trend['direction']}">{direction_zh}</span></span>
      </div>
      <div class="metric">
        <span class="metric-label">强度</span>
        <span class="metric-value">{trend['strength']}</span>
      </div>
      <div class="metric">
        <span class="metric-label">ADX</span>
        <span class="metric-value">{trend['adx']}</span>
      </div>
      <div class="metric">
        <span class="metric-label">RSI</span>
        <span class="metric-value {"red" if data["raw"]["rsi"] > 70 else "green" if data["raw"]["rsi"] < 30 else ""}">{data['raw']['rsi']}</span>
      </div>
    </div>
  </div>

  <div class="card">
    <h3>🐟 鱼身定位</h3>
    <div class="metrics-grid">
      <div class="metric">
        <span class="metric-label">阶段</span>
        <span class="metric-value">{stage_zh}</span>
      </div>
      <div class="metric">
        <span class="metric-label">启动天数</span>
        <span class="metric-value">{fish.get('trend_age_days', '-')} 天</span>
      </div>
      <div class="metric">
        <span class="metric-label">累计涨幅</span>
        <span class="metric-value">{fish.get('cumulative_pct', '-')}%</span>
      </div>
      <div class="metric">
        <span class="metric-label">偏离 EMA20</span>
        <span class="metric-value">{fish.get('deviation_pct', '-')}%</span>
      </div>
      <div class="metric">
        <span class="metric-label">理想介入</span>
        <span class="metric-value {"green" if fish.get("ideal_entry") else "red"}">{"✅ 是" if fish.get('ideal_entry') else "❌ 否"}</span>
      </div>
    </div>
  </div>

  <div class="card">
    <h3>🔄 延续动力</h3>
    <div class="metrics-grid">
      <div class="metric">
        <span class="metric-label">动能</span>
        <span class="metric-value">{momentum_zh}</span>
      </div>
      <div class="metric">
        <span class="metric-label">ADX 趋势</span>
        <span class="metric-value">{"上升 ↑" if cont["adx_rising"] else "走平/下降"}</span>
      </div>
      <div class="metric">
        <span class="metric-label">量比</span>
        <span class="metric-value">{cont['volume_ratio']}x</span>
      </div>
      <div class="metric">
        <span class="metric-label">延续判定</span>
        <span class="metric-value">{verdict_zh}</span>
      </div>
      <div class="metric" style="grid-column: 1/-1">
        <span class="metric-label">风险标记</span>
        <span class="metric-value {"yellow" if cont["risk_flags"] else ""}">{risk_flags_str}</span>
      </div>
    </div>
  </div>

  <div class="card">
    <h3>📍 关键价位</h3>
    <table class="levels-table">
      <tr><td>20 日高点</td><td>${levels['recent_high']}</td></tr>
      <tr><td>EMA20</td><td>${levels['ema20']}</td></tr>
      <tr><td>EMA50</td><td>${levels['ema50']}</td></tr>
      <tr><td>20 日低点</td><td>${levels['recent_low']}</td></tr>
      <tr><td>ATR (14)</td><td>${levels['atr']} ({levels['atr_pct']}%)</td></tr>
    </table>
  </div>

  {fund_html}
</div>

<div class="footer">
  trading-agent · 数据来源 Bitget · 仅供分析参考, 不构成投资建议
</div>

<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<script>
const chartData = {chart_json};

// --- 主图: K 线 + EMA ---
const mainEl = document.getElementById('main-chart');
const mainChart = LightweightCharts.createChart(mainEl, {{
  layout: {{ background: {{ color: '#161b22' }}, textColor: '#8b949e' }},
  grid: {{ vertLines: {{ color: '#21262d' }}, horzLines: {{ color: '#21262d' }} }},
  crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
  rightPriceScale: {{ borderColor: '#30363d', minimumWidth: 80 }},
  timeScale: {{ borderColor: '#30363d', timeVisible: false, rightOffset: 0 }},
  handleScroll: {{ vertTouchDrag: false }},
}});

const candleSeries = mainChart.addCandlestickSeries({{
  upColor: '#26a69a', downColor: '#ef5350',
  borderUpColor: '#26a69a', borderDownColor: '#ef5350',
  wickUpColor: '#26a69a', wickDownColor: '#ef5350',
}});
candleSeries.setData(chartData.candles);

const ema20Series = mainChart.addLineSeries({{
  color: '#58a6ff', lineWidth: 1.5, priceLineVisible: false,
  lastValueVisible: false,
}});
ema20Series.setData(chartData.ema20);

const ema50Series = mainChart.addLineSeries({{
  color: '#bc8cff', lineWidth: 1.5, priceLineVisible: false,
  lastValueVisible: false,
}});
ema50Series.setData(chartData.ema50);

const volumeSeries = mainChart.addHistogramSeries({{
  priceFormat: {{ type: 'volume' }},
  priceScaleId: 'vol',
}});
volumeSeries.priceScale().applyOptions({{
  scaleMargins: {{ top: 0.85, bottom: 0 }},
}});
volumeSeries.setData(chartData.volume);

// --- RSI 子图 ---
const rsiEl = document.getElementById('rsi-chart');
const rsiChart = LightweightCharts.createChart(rsiEl, {{
  layout: {{ background: {{ color: '#161b22' }}, textColor: '#8b949e' }},
  grid: {{ vertLines: {{ color: '#21262d' }}, horzLines: {{ color: '#21262d' }} }},
  rightPriceScale: {{ borderColor: '#30363d', minimumWidth: 80 }},
  timeScale: {{ borderColor: '#30363d', timeVisible: false, visible: false, rightOffset: 0 }},
  handleScroll: {{ vertTouchDrag: false }},
  crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
}});

const rsiSeries = rsiChart.addLineSeries({{
  color: '#d29922', lineWidth: 1.5,
  priceLineVisible: false, lastValueVisible: true,
}});
rsiSeries.setData(chartData.rsi);

// RSI 超买/超卖水平线
rsiSeries.createPriceLine({{ price: 70, color: 'rgba(239,83,80,0.4)', lineWidth: 1, lineStyle: 2 }});
rsiSeries.createPriceLine({{ price: 30, color: 'rgba(38,166,154,0.4)', lineWidth: 1, lineStyle: 2 }});

// --- MACD 子图 ---
const macdEl = document.getElementById('macd-chart');
const macdChart = LightweightCharts.createChart(macdEl, {{
  layout: {{ background: {{ color: '#161b22' }}, textColor: '#8b949e' }},
  grid: {{ vertLines: {{ color: '#21262d' }}, horzLines: {{ color: '#21262d' }} }},
  rightPriceScale: {{ borderColor: '#30363d', minimumWidth: 80 }},
  timeScale: {{ borderColor: '#30363d', timeVisible: false, visible: true, rightOffset: 0 }},
  handleScroll: {{ vertTouchDrag: false }},
  crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
}});

const macdHistSeries = macdChart.addHistogramSeries({{
  priceFormat: {{ type: 'price', precision: 4, minMove: 0.0001 }},
  priceLineVisible: false, lastValueVisible: false,
}});
macdHistSeries.setData(chartData.macd_hist);

const macdLineSeries = macdChart.addLineSeries({{
  color: '#58a6ff', lineWidth: 1.5,
  priceLineVisible: false, lastValueVisible: false,
}});
macdLineSeries.setData(chartData.macd_line);

const macdSignalSeries = macdChart.addLineSeries({{
  color: '#ef5350', lineWidth: 1.5, lineStyle: 2,
  priceLineVisible: false, lastValueVisible: false,
}});
macdSignalSeries.setData(chartData.macd_signal);

// 零轴
macdHistSeries.createPriceLine({{ price: 0, color: 'rgba(139,148,158,0.3)', lineWidth: 1, lineStyle: 2 }});

// --- 同步滚动 (使用 time-based range, 不用 logical range) ---
// logical range 按数据索引同步, RSI/MACD 比 K 线少前几根数据会导致错位
// time-based range 按日期同步, 无论数据长度差异都能精确对齐
let isSyncing = false;
function syncCharts(src, targets) {{
  src.timeScale().subscribeVisibleLogicalRangeChange(() => {{
    if (isSyncing) return;
    isSyncing = true;
    const range = src.timeScale().getVisibleRange();
    if (range) targets.forEach(t => t.timeScale().setVisibleRange(range));
    isSyncing = false;
  }});
}}
syncCharts(mainChart, [rsiChart, macdChart]);
syncCharts(rsiChart, [mainChart, macdChart]);
syncCharts(macdChart, [mainChart, rsiChart]);

// 主图 fitContent 后同步 time range 到子图
mainChart.timeScale().fitContent();
requestAnimationFrame(() => {{
  const range = mainChart.timeScale().getVisibleRange();
  if (range) {{
    rsiChart.timeScale().setVisibleRange(range);
    macdChart.timeScale().setVisibleRange(range);
  }}
}});

// --- 同步十字线 ---
function syncCrosshair(src, targets) {{
  src.subscribeCrosshairMove(param => {{
    if (param.time) {{
      targets.forEach(t => {{
        t.setCrosshairPosition(undefined, param.time, t.options().rightPriceScale ? undefined : undefined);
      }});
    }}
  }});
}}

// 响应式
window.addEventListener('resize', () => {{
  mainChart.applyOptions({{ width: mainEl.clientWidth }});
  rsiChart.applyOptions({{ width: rsiEl.clientWidth }});
  macdChart.applyOptions({{ width: macdEl.clientWidth }});
}});
</script>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def generate_report(ticker: str, with_fund: bool = False,
                    days: int = 90) -> Path:
    """生成 HTML 报告文件, 返回文件路径"""
    ticker = ticker.upper()

    print(f"正在获取 {ticker} 数据 ...", file=sys.stderr, flush=True)
    data = prepare_chart_data(ticker, days=days)

    fund = None
    if with_fund and HAS_FUNDAMENTALS:
        print(f"正在获取 {ticker} 基本面 ...", file=sys.stderr, flush=True)
        try:
            fund = build_fundamentals_report(ticker)
        except Exception as e:
            print(f"基本面获取失败: {e}", file=sys.stderr)

    print(f"正在生成 HTML 报告 ...", file=sys.stderr, flush=True)
    html = build_html(data, fund)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"{ticker}_{date_str}.html"
    filepath = OUTPUT_DIR / filename

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"报告已生成: {filepath}", file=sys.stderr, flush=True)
    return filepath


def build_index_html(reports: list[dict]) -> str:
    """生成索引页 HTML, reports 是 [{ticker, filepath, data, fund}, ...]"""
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = []
    for r in reports:
        d = r["data"]
        f = r.get("fund")
        close = d["price"]["close"]
        change = d["price"]["change_pct"]
        change_class = "up" if change >= 0 else "down"
        trend = d["trend"]
        fish = d["fish_body"]
        gate = d["gate"]
        direction_zh = DIRECTION_ZH.get(trend["direction"], trend["direction"])
        stage_zh = STAGE_ZH.get(fish.get("stage", "n/a"), "-")
        gate_icon = "✅" if gate["pass"] else "❌"

        # 基本面
        narrative_str = "-"
        catalyst_str = ""
        if f and f.get("status") == "success":
            n = f.get("narrative", {})
            score = n.get("score", "-")
            thesis = THESIS_ZH.get(n.get("thesis"), "-")
            narrative_str = f"{thesis}({score})"
            if n.get("earnings_catalyst"):
                catalyst_str = ' <span class="catalyst">🚀催化剂</span>'

        filename = r["filepath"].name
        rows.append(f"""
        <tr onclick="window.location='{filename}'" style="cursor:pointer">
          <td class="ticker-cell"><strong>{d['ticker']}</strong>{catalyst_str}</td>
          <td>${close}</td>
          <td class="{change_class}">{change:+.1f}%</td>
          <td>{direction_zh}</td>
          <td>{trend['adx']}</td>
          <td>{stage_zh}</td>
          <td>{narrative_str}</td>
          <td>{gate_icon}</td>
        </tr>""")

    rows_html = "\n".join(rows)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>波段分析报告汇总</title>
<style>
  :root {{
    --bg: #0d1117; --card-bg: #161b22; --border: #30363d;
    --text: #e6edf3; --text-muted: #8b949e;
    --green: #26a69a; --red: #ef5350; --blue: #58a6ff; --yellow: #d29922;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    padding: 30px; max-width: 1100px; margin: 0 auto;
  }}
  h1 {{ font-size: 1.6em; margin-bottom: 4px; }}
  .subtitle {{ color: var(--text-muted); font-size: 0.85em; margin-bottom: 24px; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--card-bg); border-radius: 12px; overflow: hidden; }}
  th {{ background: rgba(255,255,255,0.04); text-align: left; padding: 12px 16px;
       font-size: 0.78em; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; }}
  td {{ padding: 14px 16px; border-top: 1px solid var(--border); font-size: 0.95em; }}
  tr:hover td {{ background: rgba(88,166,255,0.06); }}
  .up {{ color: var(--green); font-weight: 600; }}
  .down {{ color: var(--red); font-weight: 600; }}
  .ticker-cell {{ font-size: 1.05em; }}
  .catalyst {{
    background: rgba(210,153,34,0.2); color: var(--yellow);
    padding: 2px 6px; border-radius: 4px; font-size: 0.75em; margin-left: 6px;
  }}
  .footer {{ color: var(--text-muted); font-size: 0.75em; text-align: center; margin-top: 30px; padding-top: 16px; border-top: 1px solid var(--border); }}
</style>
</head>
<body>
<h1>波段分析报告</h1>
<div class="subtitle">{len(reports)} 个品种 · {date_str} · 点击行查看详细图表</div>
<table>
  <thead>
    <tr><th>品种</th><th>价格</th><th>涨跌</th><th>趋势</th><th>ADX</th><th>鱼身</th><th>叙事</th><th>Gate</th></tr>
  </thead>
  <tbody>
    {rows_html}
  </tbody>
</table>
<div class="footer">trading-agent · 点击任意行打开完整 K 线图报告</div>
</body>
</html>"""


def generate_batch_reports(tickers: list[str], with_fund: bool = False,
                           days: int = 90) -> list[Path]:
    """批量生成报告 + 索引页, 返回所有生成的文件路径"""
    import time
    reports_meta = []
    filepaths = []

    for i, ticker in enumerate(tickers):
        ticker = ticker.upper()
        print(f"[{i+1}/{len(tickers)}] 生成 {ticker} 报告 ...", file=sys.stderr, flush=True)
        try:
            data = prepare_chart_data(ticker, days=days)
            fund = None
            if with_fund and HAS_FUNDAMENTALS:
                try:
                    fund = build_fundamentals_report(ticker)
                except Exception as e:
                    print(f"  {ticker} 基本面获取失败: {e}", file=sys.stderr)

            html = build_html(data, fund)
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            date_str = datetime.now().strftime("%Y%m%d")
            filename = f"{ticker}_{date_str}.html"
            filepath = OUTPUT_DIR / filename

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html)

            filepaths.append(filepath)
            reports_meta.append({"ticker": ticker, "filepath": filepath, "data": data, "fund": fund})

            if i < len(tickers) - 1:
                time.sleep(1.5)
        except Exception as e:
            print(f"  {ticker} 失败: {e}", file=sys.stderr)

    # 生成索引页
    if reports_meta:
        index_html = build_index_html(reports_meta)
        index_path = OUTPUT_DIR / "index.html"
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(index_html)
        filepaths.insert(0, index_path)
        print(f"索引页已生成: {index_path}", file=sys.stderr, flush=True)

    print(f"共生成 {len(filepaths)} 个文件", file=sys.stderr, flush=True)
    return filepaths


def serve_report(filepath: Path, port: int = 8765):
    """启动本地 HTTP 服务器预览报告目录"""
    serve_dir = filepath.parent
    os.chdir(serve_dir)

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # 静默日志

    server = HTTPServer(("localhost", port), Handler)
    # 如果有 index.html 就用索引页, 否则打开具体文件
    index_exists = (serve_dir / "index.html").exists()
    target = "index.html" if index_exists else filepath.name
    url = f"http://localhost:{port}/{target}"
    print(f"报告服务启动: {url}", file=sys.stderr, flush=True)
    print(f"按 Ctrl+C 停止", file=sys.stderr, flush=True)
    webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        print("\n服务已停止", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="生成带 K 线图的 HTML 交互式分析报告"
    )
    parser.add_argument("tickers",
                        help="品种代码, 逗号分隔 (如 NVDA 或 MSFT,META,AAPL)")
    parser.add_argument("--days", type=int, default=90,
                        help="数据天数 (默认: 90)")
    parser.add_argument("--with-fund", action="store_true",
                        help="包含基本面分析")
    parser.add_argument("--no-open", action="store_true",
                        help="仅生成, 不自动打开浏览器")
    parser.add_argument("--serve", action="store_true",
                        help="启动本地服务器预览")
    parser.add_argument("--port", type=int, default=8765,
                        help="服务器端口 (默认: 8765)")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]

    try:
        if len(tickers) == 1:
            # 单品种: 直接生成
            filepath = generate_report(
                tickers[0],
                with_fund=args.with_fund,
                days=args.days,
            )
            filepaths = [filepath]
        else:
            # 多品种: 批量生成 + 索引页
            filepaths = generate_batch_reports(
                tickers,
                with_fund=args.with_fund,
                days=args.days,
            )
            filepath = filepaths[0] if filepaths else None
    except (ValueError, RuntimeError) as e:
        print(json.dumps({"status": "error", "message": str(e)},
                         ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    if not filepath:
        print("未生成任何报告", file=sys.stderr)
        sys.exit(1)

    if args.serve:
        serve_report(filepath, port=args.port)
    elif not args.no_open:
        webbrowser.open(str(filepath))


if __name__ == "__main__":
    main()
