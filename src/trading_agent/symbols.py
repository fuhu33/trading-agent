"""Bitget RWA 品种同步与查询

从 Bitget 公开 API 获取所有 RWA (美股/大宗商品) 合约品种，
分类后保存到本地缓存文件。支持按分组过滤和单品种快速查询。

用法 (CLI):
    uv run trading-agent sync          # 使用缓存 (24h 有效)
    uv run trading-agent sync --force  # 强制刷新
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .exceptions import DataError
from .utils import make_request

# ---------------------------------------------------------------------------
# 分类定义
# ---------------------------------------------------------------------------

# ETF 类品种 (跟踪指数或杠杆/反向 ETF)
ETF_SYMBOLS = {
    "QQQ", "SPY", "TQQQ", "SQQQ", "SOXL", "SOXS",
    "EWH", "EWJ", "EWT", "EWY",  # 国家/地区 ETF
    "INDA", "KWEB",               # 主题 ETF
}

# 大宗商品类品种
COMMODITY_SYMBOLS = {
    "XAU",     # 黄金
    "XAG",     # 白银
    "XPD",     # 钯金
    "XPT",     # 铂金
    "COPPER",  # 铜
    "NATGAS",  # 天然气
}

# 其余 isRwa == YES 的品种默认归为美股个股 (stock)

# 路径相对于项目根目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = _PROJECT_ROOT / "config"
CACHE_FILE = CACHE_DIR / "bitget_symbols.json"
CACHE_TTL_SECONDS = 24 * 3600  # 24 小时

API_URL = "https://api.bitget.com/api/v2/mix/market/contracts?productType=USDT-FUTURES"

# 内存索引 (模块级单例, 避免重复线性扫描)
_SYMBOL_INDEX: dict[str, dict] | None = None


# ---------------------------------------------------------------------------
# 核心逻辑
# ---------------------------------------------------------------------------

def classify_symbol(base_coin: str) -> str:
    """根据 baseCoin 判断分组"""
    if base_coin in ETF_SYMBOLS:
        return "etf"
    if base_coin in COMMODITY_SYMBOLS:
        return "commodity"
    return "stock"


def fetch_from_api() -> list[dict]:
    """从 Bitget API 获取并过滤 RWA 品种"""
    data = make_request(API_URL)

    if data.get("code") != "00000":
        raise DataError(f"Bitget API 返回错误: {data.get('msg')}")

    rwa_symbols = []
    for contract in data["data"]:
        if contract.get("isRwa") != "YES":
            continue

        base_coin = contract["baseCoin"]
        rwa_symbols.append({
            "baseCoin": base_coin,
            "symbol": contract["symbol"],
            "maxLever": int(contract.get("maxLever", 1)),
            "status": contract.get("symbolStatus", "unknown"),
            "group": classify_symbol(base_coin),
            "minTradeUSDT": float(contract.get("minTradeUSDT", 5)),
        })

    # 按 group 分组后按字母排序
    rwa_symbols.sort(key=lambda x: (x["group"], x["baseCoin"]))
    return rwa_symbols


def save_cache(symbols: list[dict]) -> dict:
    """保存到缓存文件，返回完整报告"""
    report = {
        "status": "success",
        "source": "bitget_api",
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "total": len(symbols),
        "groups": {
            "stock": len([s for s in symbols if s["group"] == "stock"]),
            "etf": len([s for s in symbols if s["group"] == "etf"]),
            "commodity": len([s for s in symbols if s["group"] == "commodity"]),
        },
        "symbols": symbols,
    }

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return report


def load_cache() -> dict | None:
    """加载缓存文件，过期则返回 None"""
    if not CACHE_FILE.exists():
        return None

    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    # 检查缓存是否过期
    synced_at = data.get("synced_at", "")
    if not synced_at:
        return None

    try:
        synced_time = datetime.fromisoformat(synced_at)
        age = (datetime.now(timezone.utc) - synced_time).total_seconds()
        if age > CACHE_TTL_SECONDS:
            return None
    except ValueError:
        return None

    data["source"] = "cache"
    return data


def get_symbols(force: bool = False) -> dict:
    """获取品种列表 (优先缓存)"""
    if not force:
        cached = load_cache()
        if cached is not None:
            return cached

    symbols = fetch_from_api()
    return save_cache(symbols)


def _build_index(symbols: list[dict]) -> dict[str, dict]:
    """构建 baseCoin -> info 索引"""
    return {s["baseCoin"].upper(): s for s in symbols}


def lookup_symbol(base_coin: str) -> dict | None:
    """查找单个品种，O(1) 索引查找

    首次调用时从缓存构建索引，后续直接查 dict。
    """
    global _SYMBOL_INDEX
    if _SYMBOL_INDEX is None:
        report = get_symbols()
        _SYMBOL_INDEX = _build_index(report["symbols"])
    return _SYMBOL_INDEX.get(base_coin.upper())


def invalidate_index() -> None:
    """清除内存索引 (force refresh 后需调用)"""
    global _SYMBOL_INDEX
    _SYMBOL_INDEX = None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="同步 Bitget RWA 合约品种列表")
    parser.add_argument("--force", action="store_true", help="强制刷新 (忽略缓存)")
    parser.add_argument("--group", choices=["stock", "etf", "commodity", "all"],
                        default="all", help="过滤分组 (默认: all)")
    parser.add_argument("--quiet", action="store_true", help="仅输出 baseCoin 列表")
    args = parser.parse_args()

    try:
        if args.force:
            invalidate_index()
        report = get_symbols(force=args.force)
    except DataError as e:
        print(json.dumps({"status": "error", "message": str(e)},
                         ensure_ascii=False))
        sys.exit(1)

    # 按分组过滤
    if args.group != "all":
        report["symbols"] = [s for s in report["symbols"] if s["group"] == args.group]
        report["total"] = len(report["symbols"])

    if args.quiet:
        for s in report["symbols"]:
            print(s["baseCoin"])
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
