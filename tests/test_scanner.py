"""scanner 模块单元测试

覆盖:
  - resolve_tickers 分组解析
  - format_table 输出格式
"""

import pytest

from trading_agent.scanner import resolve_tickers, MEGA_CAP, format_table


# ---------------------------------------------------------------------------
# resolve_tickers
# ---------------------------------------------------------------------------

class TestResolveTickers:
    def test_csv_input(self):
        """逗号分隔输入应正确解析"""
        result = resolve_tickers("aapl, msft, nvda", "all")
        assert result == ["AAPL", "MSFT", "NVDA"]

    def test_csv_with_spaces(self):
        """应处理空格和空值"""
        result = resolve_tickers("AAPL, , MSFT, ", "all")
        assert result == ["AAPL", "MSFT"]

    def test_csv_overrides_group(self):
        """有 tickers_csv 时忽略 group"""
        result = resolve_tickers("AAPL", "mega_cap")
        assert result == ["AAPL"]


# ---------------------------------------------------------------------------
# format_table
# ---------------------------------------------------------------------------

class TestFormatTable:
    def _make_result(self, ticker="AAPL", gate_pass=True, **overrides):
        base = {
            "status": "success",
            "ticker": ticker,
            "group": "stock",
            "close": 200.0,
            "change_pct": 1.5,
            "direction": "bullish",
            "strength": "strong",
            "adx": 30.0,
            "rsi": 55.0,
            "macd_hist": 0.5,
            "momentum": "accelerating",
            "volume_ratio": 1.2,
            "verdict": "strong",
            "risk_flags": [],
            "stage": "mid",
            "trend_age_days": 15,
            "cumulative_pct": 12.0,
            "deviation_pct": 5.0,
            "ideal_entry": True,
            "gate_pass": gate_pass,
            "gate_reason": "ADX=30 >= 20, direction=bullish",
        }
        base.update(overrides)
        return base

    def test_basic_table(self):
        """基础表格应包含表头和数据行"""
        results = [self._make_result()]
        output = format_table(results)
        assert "AAPL" in output
        assert "品种" in output
        assert "✅" in output

    def test_error_row(self):
        """错误品种应显示 ERROR"""
        results = [{"status": "error", "ticker": "BAD", "message": "fail"}]
        output = format_table(results)
        assert "ERROR" in output

    def test_summary_line(self):
        """应包含扫描汇总"""
        results = [
            self._make_result("AAPL", gate_pass=True),
            self._make_result("INTC", gate_pass=False),
        ]
        output = format_table(results)
        assert "扫描完成" in output
        assert "通过 1" in output

    def test_ideal_entry_star(self):
        """ideal_entry=True 应有 ⭐ 标记"""
        results = [self._make_result(ideal_entry=True)]
        output = format_table(results)
        assert "⭐" in output
