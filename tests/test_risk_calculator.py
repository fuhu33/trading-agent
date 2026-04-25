"""risk_calculator 单元测试"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from risk_calculator import calculate_risk


# ---------------------------------------------------------------------------
# 基础计算正确性
# ---------------------------------------------------------------------------

class TestBasicLong:
    """多头仓位计算"""

    def test_standard_long(self):
        """entry=150, stop=142, account=100000, risk=2%"""
        r = calculate_risk(entry=150, stop=142, account=100000, risk_pct=0.02)
        assert r["status"] == "success"
        assert r["direction"] == "long"
        assert r["risk_per_share"] == 8.0
        assert r["risk_amount"] == 2000.0
        assert r["position_size"] == 250.0  # 2000 / 8
        assert r["position_value"] == 37500.0  # 250 * 150
        assert r["max_loss"] == 2000.0
        assert r["targets"]["2r"] == 166.0  # 150 + 2*8
        assert r["targets"]["3r"] == 174.0  # 150 + 3*8

    def test_no_leverage_warning(self):
        """仓位市值 < 账户 → 无 warnings"""
        r = calculate_risk(entry=150, stop=142, account=100000, risk_pct=0.02)
        assert "warnings" not in r


class TestBasicShort:
    """空头仓位计算"""

    def test_standard_short(self):
        """entry=100, stop=108, account=100000, risk=2%"""
        r = calculate_risk(entry=100, stop=108, account=100000, risk_pct=0.02)
        assert r["direction"] == "short"
        assert r["risk_per_share"] == 8.0
        assert r["position_size"] == 250.0
        assert r["targets"]["2r"] == 84.0   # 100 - 2*8
        assert r["targets"]["3r"] == 76.0   # 100 - 3*8


# ---------------------------------------------------------------------------
# 杠杆警告
# ---------------------------------------------------------------------------

class TestLeverageWarning:
    """止损窄导致仓位市值超账户"""

    def test_tight_stop_triggers_warning(self):
        """entry=100, stop=99 → position_value=200000 > account"""
        r = calculate_risk(entry=100, stop=99, account=100000, risk_pct=0.02)
        assert r["position_size"] == 2000.0  # 2000 / 1
        assert r["position_value"] == 200000.0
        assert "warnings" in r
        assert "杠杆" in r["warnings"][0]

    def test_wide_stop_no_warning(self):
        """entry=100, stop=80 → position_value=10000 < account"""
        r = calculate_risk(entry=100, stop=80, account=100000, risk_pct=0.02)
        assert r["position_value"] == 10000.0  # 100 shares * $100
        assert "warnings" not in r


# ---------------------------------------------------------------------------
# ATR 辅助
# ---------------------------------------------------------------------------

class TestATR:
    def test_atr_multiple(self):
        r = calculate_risk(entry=150, stop=142, atr=3.5)
        assert r["atr"] == 3.5
        assert r["stop_atr_multiple"] == round(8.0 / 3.5, 2)

    def test_atr_zero(self):
        r = calculate_risk(entry=150, stop=142, atr=0)
        assert r["stop_atr_multiple"] is None

    def test_no_atr(self):
        r = calculate_risk(entry=150, stop=142)
        assert "atr" not in r


# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------

class TestValidation:
    def test_entry_zero(self):
        with pytest.raises(ValueError, match="入场价"):
            calculate_risk(entry=0, stop=10)

    def test_stop_zero(self):
        with pytest.raises(ValueError, match="止损价"):
            calculate_risk(entry=10, stop=0)

    def test_entry_equals_stop(self):
        with pytest.raises(ValueError, match="不能相同"):
            calculate_risk(entry=100, stop=100)

    def test_account_negative(self):
        with pytest.raises(ValueError, match="账户资金"):
            calculate_risk(entry=100, stop=90, account=-1)

    def test_risk_pct_too_high(self):
        with pytest.raises(ValueError, match="风险比例"):
            calculate_risk(entry=100, stop=90, risk_pct=0.2)

    def test_risk_pct_zero(self):
        with pytest.raises(ValueError, match="风险比例"):
            calculate_risk(entry=100, stop=90, risk_pct=0)
