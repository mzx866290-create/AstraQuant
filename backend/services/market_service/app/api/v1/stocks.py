"""
股票列表 API
"""
import os
import sys
from datetime import datetime
from fastapi import APIRouter, Query, HTTPException
from typing import Optional

router = APIRouter(tags=["股票列表"])

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../.."))
sys.path.insert(0, _PROJECT_ROOT)


def _api_symbol(symbol: str, market: str) -> str:
    code = symbol[:6] if symbol else ""
    return f"{code}.{market or ('SH' if code.startswith(('6', '9')) else 'SZ')}"


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_list_date(value):
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt)
        except ValueError:
            continue
    return None


def _fetch_public_stock_info(code: str) -> dict:
    """Fetch public stock profile from AKShare/EastMoney as a fallback."""
    try:
        import akshare as ak

        df = ak.stock_individual_info_em(symbol=code)
        if df is None or df.empty:
            return {}
        raw = {
            str(row.get("item", "")): row.get("value")
            for _, row in df.iterrows()
        }
        list_date = _parse_list_date(raw.get("上市时间"))
        return {
            "code": code,
            "name": str(raw.get("股票简称") or ""),
            "sector": str(raw.get("行业") or ""),
            "latest_price": _safe_float(raw.get("最新")),
            "total_shares": _safe_float(raw.get("总股本")),
            "float_shares": _safe_float(raw.get("流通股")),
            "total_mv": _safe_float(raw.get("总市值")),
            "circ_mv": _safe_float(raw.get("流通市值")),
            "list_date": list_date.isoformat() if list_date else None,
            "source": "akshare",
        }
    except Exception:
        pass

    company_info = {}
    try:
        import requests

        em_code = f"{'SH' if code.startswith(('6', '9')) else 'SZ'}{code}"
        resp = requests.get(
            "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax",
            params={"code": em_code},
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://emweb.securities.eastmoney.com/",
            },
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        base = (payload.get("jbzl") or [{}])[0]
        issue = (payload.get("fxxg") or [{}])[0]
        list_date = _parse_list_date(issue.get("LISTING_DATE"))
        company_info = {
            "name": base.get("SECURITY_NAME_ABBR") or "",
            "sector": (base.get("EM2016") or "").split("-")[0],
            "list_date": list_date.isoformat() if list_date else None,
        }
    except Exception:
        company_info = {}

    try:
        import requests

        prefix = "sh" if code.startswith(("6", "9")) else "sz"
        resp = requests.get(
            f"https://qt.gtimg.cn/q={prefix}{code}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        resp.raise_for_status()
        body = resp.text.split('="', 1)[1].rsplit('"', 1)[0]
        parts = body.split("~")
        if len(parts) < 74 or not parts[2]:
            return {}
        return {
            "code": code,
            "name": company_info.get("name") or parts[1],
            "sector": company_info.get("sector") or "",
            "latest_price": _safe_float(parts[3]),
            "total_shares": _safe_float(parts[73]),
            "float_shares": _safe_float(parts[72]),
            "total_mv": (_safe_float(parts[45]) or 0) * 1e8 if _safe_float(parts[45]) is not None else None,
            "circ_mv": (_safe_float(parts[44]) or 0) * 1e8 if _safe_float(parts[44]) is not None else None,
            "list_date": company_info.get("list_date"),
            "source": "eastmoney+tencent" if company_info else "tencent",
        }
    except Exception:
        if company_info:
            return {
                "code": code,
                "name": company_info.get("name", ""),
                "sector": company_info.get("sector", ""),
                "latest_price": None,
                "total_shares": None,
                "float_shares": None,
                "total_mv": None,
                "circ_mv": None,
                "list_date": company_info.get("list_date"),
                "source": "eastmoney",
            }
        return {}


@router.get("")
async def get_stocks(
    market: Optional[str] = Query(None, description="市场筛选: SH/SZ"),
    limit: int = Query(50, ge=1, le=500, description="返回条数"),
):
    """获取A股股票列表"""
    try:
        from backend.shared.database import SessionLocal
        from backend.shared.models import Stock

        db = SessionLocal()
        try:
            query = db.query(Stock).filter(Stock.is_active == True)
            if market:
                query = query.filter(Stock.market == market)
            stocks = query.limit(limit * 2).all()
            seen_codes = set()
            items = []
            for s in stocks:
                code = s.symbol[:6]
                if code in seen_codes:
                    continue
                seen_codes.add(code)
                items.append({
                    "id": s.id,
                    "symbol": _api_symbol(s.symbol, s.market),
                    "name": s.name,
                    "market": s.market,
                    "sector": s.sector,
                })
                if len(items) >= limit:
                    break
            return {
                "stocks": items,
                "total": len(items),
            }
        finally:
            db.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取股票列表失败: {str(e)}")


@router.get("/{symbol}")
async def get_stock(symbol: str):
    """获取A股股票基本信息"""
    if not symbol or len(symbol) < 6:
        raise HTTPException(status_code=400, detail="无效的股票代码")

    code = symbol[:6] if len(symbol) >= 6 else symbol
    market = "SH" if code.startswith(("6", "9")) else "SZ"
    public_info = _fetch_public_stock_info(code)

    try:
        from backend.shared.database import SessionLocal
        from backend.shared.models import Stock

        db = SessionLocal()
        try:
            stock = db.query(Stock).filter(Stock.symbol.like(f"{code}%")).first()
            if stock:
                list_date = stock.list_date.isoformat() if stock.list_date else public_info.get("list_date")
                return {
                    "id": stock.id,
                    "symbol": _api_symbol(stock.symbol, stock.market),
                    "code": code,
                    "name": stock.name or public_info.get("name", ""),
                    "market": stock.market,
                    "sector": stock.sector or public_info.get("sector", ""),
                    "list_date": list_date,
                    "latest_price": public_info.get("latest_price"),
                    "total_shares": public_info.get("total_shares"),
                    "float_shares": public_info.get("float_shares"),
                    "total_mv": public_info.get("total_mv"),
                    "circ_mv": public_info.get("circ_mv"),
                    "source": f"database+{public_info.get('source')}" if public_info else "database",
                }
        finally:
            db.close()
    except Exception:
        pass

    return {
        "symbol": f"{code}.{market}",
        "code": code,
        "market": market,
        "name": public_info.get("name", ""),
        "sector": public_info.get("sector", ""),
        "list_date": public_info.get("list_date"),
        "latest_price": public_info.get("latest_price"),
        "total_shares": public_info.get("total_shares"),
        "float_shares": public_info.get("float_shares"),
        "total_mv": public_info.get("total_mv"),
        "circ_mv": public_info.get("circ_mv"),
        "source": public_info.get("source", "fallback"),
    }
