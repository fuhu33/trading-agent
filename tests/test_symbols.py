"""symbols 模块单元测试"""

from trading_agent.symbols import classify_symbol


class TestClassifySymbol:
    def test_known_equity_etf_and_commodity_groups(self):
        assert classify_symbol("NVDA") == "stock"
        assert classify_symbol("QQQ") == "etf"
        assert classify_symbol("XAU") == "commodity"

    def test_gold_backed_tokens_are_not_stock(self):
        assert classify_symbol("PAXG") == "commodity"
        assert classify_symbol("XAUT") == "commodity"
