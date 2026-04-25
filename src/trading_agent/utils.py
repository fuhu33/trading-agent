"""共用工具函数

消除各模块中重复的 _safe / _safe_float / make_request 等逻辑。
"""

import json
import urllib.request
from math import isnan

import numpy as np


def safe_float(v, default: float = 0.0) -> float:
    """安全地将值转为 float，NaN / None 返回 default

    替代各模块中零散的 _safe lambda。
    """
    if v is None:
        return default
    try:
        f = float(v)
        if f != f or (isinstance(v, float) and isnan(v)):  # NaN check
            return default
        return f
    except (TypeError, ValueError):
        return default


def safe_np_float(v, default: float = 0.0) -> float:
    """针对 numpy 标量的安全转换"""
    try:
        if np.isnan(v):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def make_request(url: str, timeout: int = 15) -> dict:
    """统一的 HTTP GET 请求封装

    Args:
        url: 请求 URL
        timeout: 超时秒数

    Returns:
        解析后的 JSON dict

    Raises:
        trading_agent.exceptions.DataError: 请求失败
    """
    from .exceptions import DataError

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "trading-agent/0.2"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        raise DataError(f"HTTP 请求失败: {url} — {e}") from e
