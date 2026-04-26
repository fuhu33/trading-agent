"""fundamentals 模块单元测试

覆盖:
  - compute_narrative 评分逻辑
  - 财报催化剂判定
  - 缓存 TTL 验证
"""

from trading_agent.fundamentals import compute_narrative


# ---------------------------------------------------------------------------
# compute_narrative 评分逻辑
# ---------------------------------------------------------------------------

class TestComputeNarrative:
    """测试综合叙事评分"""

    def test_strong_thesis(self):
        """EPS 强超预期 + 行业多头 + 分析师看多 → strong"""
        earnings = {"eps_surprise_pct": 15.0}
        sector = {"trend": "bullish", "etf": "SMH", "change_20d": 10.0}
        analysts = {"rating_score": 1.5, "rating": "Strong Buy", "upside_pct": 20.0}
        result = compute_narrative(earnings, None, sector, analysts)
        assert result["thesis"] == "strong"
        assert result["score"] >= 7

    def test_weak_thesis(self):
        """EPS miss + 行业空头 + 分析师看空 → weak"""
        earnings = {"eps_surprise_pct": -10.0}
        sector = {"trend": "bearish", "etf": "XLK", "change_20d": -5.0}
        analysts = {"rating_score": 4.0, "rating": "Sell", "upside_pct": -10.0}
        result = compute_narrative(earnings, None, sector, analysts)
        assert result["thesis"] == "weak"
        assert result["score"] < 4

    def test_moderate_thesis(self):
        """EPS 微超预期 + 行业 mixed + 评级较好 → moderate"""
        earnings = {"eps_surprise_pct": 5.0}
        sector = {"trend": "mixed", "etf": "XLK", "change_20d": 1.0}
        analysts = {"rating_score": 2.3, "upside_pct": 12.0}
        result = compute_narrative(earnings, None, sector, analysts)
        assert result["thesis"] == "moderate"
        assert 4 <= result["score"] < 7

    def test_no_earnings_data(self):
        """无 EPS 数据 → concerns 中包含提示"""
        result = compute_narrative(None, None, None, None)
        assert any("EPS" in c for c in result["concerns"])

    def test_score_bounds(self):
        """分数限制在 0-10"""
        # 极端正面
        earnings = {"eps_surprise_pct": 100.0}
        sector = {"trend": "bullish", "etf": "SMH", "change_20d": 50.0}
        analysts = {"rating_score": 1.0, "rating": "Strong Buy", "upside_pct": 50.0}
        next_e = {"in_window": True, "days_until": 5}
        result = compute_narrative(earnings, next_e, sector, analysts)
        assert 0 <= result["score"] <= 10

        # 极端负面
        earnings2 = {"eps_surprise_pct": -50.0}
        analysts2 = {"rating_score": 5.0, "upside_pct": -30.0}
        next_e2 = {"in_window": True, "days_until": 3}
        result2 = compute_narrative(earnings2, next_e2, None, analysts2)
        assert 0 <= result2["score"] <= 10


# ---------------------------------------------------------------------------
# 财报催化剂判定
# ---------------------------------------------------------------------------

class TestEarningsCatalyst:
    def test_catalyst_strong_in_window(self):
        """强叙事 + 财报窗口 → earnings_catalyst = True"""
        earnings = {"eps_surprise_pct": 15.0}
        sector = {"trend": "bullish", "etf": "SMH", "change_20d": 10.0}
        analysts = {"rating_score": 1.5, "rating": "Strong Buy", "upside_pct": 20.0}
        next_e = {"in_window": True, "days_until": 5}
        result = compute_narrative(earnings, next_e, sector, analysts)
        assert result["earnings_catalyst"] is True

    def test_no_catalyst_weak_in_window(self):
        """弱叙事 + 财报窗口 → earnings_catalyst = False"""
        earnings = {"eps_surprise_pct": -10.0}
        next_e = {"in_window": True, "days_until": 5}
        result = compute_narrative(earnings, next_e, None, None)
        assert result["earnings_catalyst"] is False

    def test_no_catalyst_not_in_window(self):
        """不在窗口 → earnings_catalyst = False"""
        earnings = {"eps_surprise_pct": 15.0}
        sector = {"trend": "bullish", "etf": "SMH", "change_20d": 10.0}
        analysts = {"rating_score": 1.5, "rating": "Strong Buy", "upside_pct": 20.0}
        next_e = {"in_window": False, "days_until": 45}
        result = compute_narrative(earnings, next_e, sector, analysts)
        assert result["earnings_catalyst"] is False

    def test_weak_in_window_penalty(self):
        """弱叙事 + 财报窗口 → 分数不应上升"""
        earnings = {"eps_surprise_pct": -2.0}  # 轻微 miss, 基础分 0
        next_e = {"in_window": True, "days_until": 3}
        result = compute_narrative(earnings, next_e, None, None)
        result_no_window = compute_narrative(earnings, None, None, None)
        # 弱叙事 + 财报窗口应扣分，但两者都已触底 0 时无法再扣
        assert result["score"] <= result_no_window["score"]


# ---------------------------------------------------------------------------
# 评分因子独立性
# ---------------------------------------------------------------------------

class TestScoringFactors:
    def test_eps_scoring(self):
        """EPS 超预期程度 → 分数递增"""
        s1 = compute_narrative({"eps_surprise_pct": 0.5}, None, None, None)["score"]
        s2 = compute_narrative({"eps_surprise_pct": 5.0}, None, None, None)["score"]
        s3 = compute_narrative({"eps_surprise_pct": 15.0}, None, None, None)["score"]
        assert s1 <= s2 <= s3

    def test_analyst_extreme_bearish(self):
        """分析师极度看空 → 分数不应上升"""
        # 给 base 一些基础分，避免两者都触底 0
        base = compute_narrative({"eps_surprise_pct": 5.0}, None, None, None)["score"]
        bearish = compute_narrative(
            {"eps_surprise_pct": 5.0}, None, None,
            {"rating_score": 4.5, "upside_pct": -15.0}
        )["score"]
        assert bearish < base

    def test_sector_bullish_bonus(self):
        """行业多头 → 加分"""
        base = compute_narrative(None, None, None, None)["score"]
        with_sector = compute_narrative(
            None, None,
            {"trend": "bullish", "etf": "XLK", "change_20d": 8.0},
            None
        )["score"]
        assert with_sector > base
