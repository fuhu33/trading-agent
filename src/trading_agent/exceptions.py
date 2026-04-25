"""统一异常层级

所有模块使用这些异常替代零散的 ValueError / RuntimeError，
方便上层 CLI 和 Agent 统一捕获和格式化输出。
"""


class TradingAgentError(Exception):
    """基础异常 — 所有 trading-agent 异常的父类"""


class DataError(TradingAgentError):
    """数据获取或解析失败

    场景: API 超时、返回格式异常、数据不足等。
    """


class ValidationError(TradingAgentError):
    """参数校验失败

    场景: ticker 不在品种列表、entry == stop、risk_pct 超限等。
    """


class CacheError(TradingAgentError):
    """缓存读写异常

    场景: 缓存文件损坏、权限不足等。非致命错误，可降级为重新获取。
    """
