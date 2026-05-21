"""
搜索API - 本地数据库搜索
"""
import os
import re
import sys
from fastapi import APIRouter, Query, HTTPException
from typing import Optional

router = APIRouter(tags=["搜索"])

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../.."))
sys.path.insert(0, _PROJECT_ROOT)

from backend.services.market_service.app.utils.symbols import bj_legacy_920_symbol, extract_code as _shared_extract_code


def _count_query(query) -> int:
    count = getattr(query, "count", None)
    if callable(count):
        return count()

    rows = query.all()
    try:
        return len(rows)
    except TypeError:
        return 0


def _keyword_variants(keyword: str) -> list[str]:
    """Keep searches forgiving for 600519, 600519.SH, SH600519 and names."""
    raw = keyword.strip()
    upper = raw.upper()
    variants = [raw]
    if upper != raw:
        variants.append(upper)

    code_match = re.search(r"\d{6}", upper)
    if code_match:
        code = code_match.group(0)
        variants.extend([code, f"{code}.SH", f"{code}.SZ", f"{code}.BJ", f"SH{code}", f"SZ{code}", f"BJ{code}"])
        alias = bj_legacy_920_symbol(upper)
        alias_code = _shared_extract_code(alias)
        if alias_code:
            variants.extend([alias_code, f"{alias_code}.BJ", f"BJ{alias_code}"])

    return list(dict.fromkeys(item for item in variants if item))


def _extract_code(symbol: str) -> str:
    match = re.search(r"\d{6}", (symbol or "").upper())
    return match.group(0) if match else ""


def _api_symbol(symbol: str, market: str) -> str:
    code = _extract_code(symbol)
    return f"{code}.{market}" if code else symbol


def _is_exact_symbol_keyword(keyword: str) -> bool:
    upper = keyword.strip().upper()
    return bool(re.fullmatch(r"(SH|SZ|BJ)?\d{6}(\.(SH|SS|SZ|BJ))?", upper))


def _fallback_exact_symbol(keyword: str, market_filter: Optional[str]) -> Optional[dict]:
    if not _is_exact_symbol_keyword(keyword):
        return None

    code = _extract_code(keyword)
    if len(code) != 6:
        return None

    from backend.services.market_service.app.api.v1 import stocks

    requested_market = stocks._extract_market(keyword)
    inferred_market = stocks._infer_market(code, market_filter or requested_market)
    if market_filter and market_filter != "ALL" and inferred_market != market_filter:
        return None

    alias_symbol = bj_legacy_920_symbol(keyword, inferred_market)
    resolved_code = _extract_code(alias_symbol) if alias_symbol else code
    public_info = stocks._fetch_public_stock_info(resolved_code, inferred_market)
    return {
        "symbol": f"{resolved_code}.{inferred_market}",
        "name": public_info.get("name") or code,
        "market": inferred_market,
        "pinyin": "",
        "source": public_info.get("source", "fallback"),
    }


def _dedupe_legacy_bj_aliases(results: list[dict], preferred_code: str) -> list[dict]:
    if not preferred_code or not any(_extract_code(item.get("symbol", "")) == preferred_code for item in results):
        return results
    deduped = []
    for item in results:
        symbol = item.get("symbol", "")
        code = _extract_code(symbol)
        if code != preferred_code and _extract_code(bj_legacy_920_symbol(symbol, item.get("market"))) == preferred_code:
            continue
        deduped.append(item)
    return deduped


@router.get("")
async def search_stocks(
    q: str = Query(..., min_length=1, max_length=50, description="搜索关键词"),
    market: Optional[str] = Query(None, description="市场筛选: SH/SZ/BJ"),
    limit: int = Query(20, ge=1, le=100, description="返回条数"),
):
    """搜索A股股票（本地数据库）"""
    from backend.shared.cache import get_cache_manager
    from backend.shared.database import SessionLocal
    from backend.shared.models import Stock

    keyword = q.strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="请输入搜索关键词")

    market_filter = market.upper() if market else None
    cache_key = f"v4:{keyword}:{market_filter or 'ALL'}:{limit}"
    cache = await get_cache_manager()
    cached = await cache.get("search_result", cache_key)
    if cached is not None:
        return cached

    db = SessionLocal()
    try:
        conditions = [Stock.name.like(f"%{keyword}%")]
        for variant in _keyword_variants(keyword):
            conditions.append(Stock.symbol.like(f"%{variant}%"))

        condition = conditions[0]
        for item in conditions[1:]:
            condition = condition | item

        query = db.query(Stock).filter(condition)
        if market_filter and market_filter != "ALL":
            query = query.filter(Stock.market == market_filter)
        total = _count_query(query)
        stocks = query.limit(limit * 2).all()

        results = []
        seen_codes = set()
        for s in stocks:
            code = _extract_code(s.symbol)
            if code in seen_codes:
                continue
            seen_codes.add(code)
            results.append({
                "symbol": _api_symbol(s.symbol, s.market),
                "name": s.name,
                "market": s.market,
                "pinyin": "",
            })

        fallback = _fallback_exact_symbol(keyword, market_filter)
        if fallback and fallback["symbol"] not in {item["symbol"] for item in results}:
            results.append(fallback)
            total = max(total, len(results))

        preferred_code = _shared_extract_code(bj_legacy_920_symbol(keyword, market_filter))
        if preferred_code:
            results.sort(key=lambda item: 0 if _extract_code(item.get("symbol", "")) == preferred_code else 1)
            results = _dedupe_legacy_bj_aliases(results, preferred_code)
            total = len(results)
        results = results[:limit]

        response = {"results": results, "total": total, "count": len(results), "query": q}
        await cache.set("search_result", cache_key, value=response)
        return response
    finally:
        db.close()
