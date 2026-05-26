"""
自选股 API - 多分组管理
"""
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.shared.database import get_db
from backend.shared.models import Watchlist, WatchlistItem, Stock, User
from backend.shared.schemas import (
    WatchlistCreate, WatchlistResponse, WatchlistItemResponse,
)
from backend.shared.exceptions import raise_not_found, raise_bad_request
from backend.shared.auth import get_current_user

router = APIRouter(prefix="/watchlists", tags=["自选股"])


class AddItemRequest(BaseModel):
    stock_id: Optional[int] = None
    symbol: Optional[str] = None
    name: Optional[str] = None
    market: Optional[str] = None
    sector: Optional[str] = None


class ReorderItemsRequest(BaseModel):
    stock_ids: List[int]


class BatchAddRequest(BaseModel):
    symbols: List[str]


def _api_symbol(stock: Stock) -> str:
    code = stock.symbol[:6]
    return f"{code}.{stock.market}"


def _normalize_stock_code(symbol: str | None) -> str:
    """Extract a 6-digit A-share code from 600519, 600519.SH, or SH600519."""
    match = re.search(r"\d{6}", (symbol or "").strip().upper())
    return match.group(0) if match else ""


def _infer_market(code: str) -> str:
    if code.startswith("920"):
        return "BJ"
    if code.startswith(("6", "9", "5")):
        return "SH"
    if code.startswith(("0", "1", "2", "3")):
        return "SZ"
    if code.startswith(("4", "8")):
        return "BJ"
    return ""


def _clean_optional_text(value: str | None, max_length: int) -> str | None:
    text = (value or "").strip()
    if _is_placeholder_text(text):
        return None
    return text[:max_length] if text else None


def _is_placeholder_text(value: str | None) -> bool:
    text = (value or "").strip()
    if not text:
        return True
    if set(text) <= {"?", "？", "�"}:
        return True
    return text.lower() in {"unknown", "null", "none", "nan"}


def _stock_display_name(stock: Stock | None) -> str:
    if not stock:
        return ""
    code = stock.symbol[:6]
    return code if _is_placeholder_text(stock.name) else stock.name


def _find_stock_by_code(db: Session, code: str) -> Optional[Stock]:
    return db.query(Stock).filter(Stock.symbol.like(f"{code}%")).first()


def _ensure_stock_for_symbol(db: Session, body: AddItemRequest) -> Stock:
    symbol = body.symbol
    code = _normalize_stock_code(symbol)
    if not code:
        raise_bad_request("请输入有效的6位股票代码")

    stock = _find_stock_by_code(db, code)
    if stock:
        fallback_name = _clean_optional_text(body.name, 100)
        fallback_sector = _clean_optional_text(body.sector, 100)
        if fallback_name and (stock.name == stock.symbol[:6] or _is_placeholder_text(stock.name)):
            stock.name = fallback_name
        if fallback_sector and not stock.sector:
            stock.sector = fallback_sector
        return stock

    market = (body.market or "").strip().upper()
    if market not in {"SH", "SZ", "BJ"}:
        market = _infer_market(code)
    if not market:
        raise_bad_request("暂只支持A股6位股票代码")

    stock = Stock(
        symbol=code,
        name=_clean_optional_text(body.name, 100) or code,
        market=market,
        sector=_clean_optional_text(body.sector, 100),
        is_active=True,
    )
    db.add(stock)
    db.flush()
    return stock


@router.get("")
async def get_watchlists(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取用户所有自选股分组（含股票列表）"""
    lists = (
        db.query(Watchlist)
        .filter(Watchlist.user_id == current_user.id)
        .order_by(Watchlist.sort_order)
        .all()
    )
    if not lists:
        # 自动创建默认分组
        wl = Watchlist(user_id=current_user.id, name="默认分组", sort_order=0)
        db.add(wl)
        db.commit()
        db.refresh(wl)
        lists = [wl]

    result = []
    for wl in lists:
        items = (
            db.query(WatchlistItem)
            .filter(WatchlistItem.watchlist_id == wl.id)
            .order_by(WatchlistItem.sort_order, WatchlistItem.id)
            .all()
        )
        stock_ids = {item.stock_id for item in items}
        stocks_map = {s.id: s for s in db.query(Stock).filter(Stock.id.in_(stock_ids)).all()} if stock_ids else {}

        item_data = []
        for item in items:
            stock = stocks_map.get(item.stock_id)
            item_data.append({
                "id": item.id,
                "stock_id": item.stock_id,
                "symbol": _api_symbol(stock) if stock else "",
                "name": _stock_display_name(stock),
                "market": stock.market if stock else "",
                "sector": stock.sector if stock else "",
                "sort_order": item.sort_order,
                "added_at": item.added_at.isoformat() if item.added_at else None,
            })
        result.append({
            "id": wl.id,
            "user_id": wl.user_id,
            "name": wl.name,
            "sort_order": wl.sort_order,
            "created_at": wl.created_at.isoformat() if wl.created_at else None,
            "items": item_data,
        })
    return result


@router.post("")
async def create_watchlist(
    data: WatchlistCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建自选股分组"""
    existing = db.query(Watchlist).filter(
        Watchlist.user_id == current_user.id,
        Watchlist.name == data.name,
    ).first()
    if existing:
        raise_bad_request("分组名称已存在")

    watchlist = Watchlist(user_id=current_user.id, name=data.name)
    db.add(watchlist)
    db.commit()
    db.refresh(watchlist)
    return {
        "id": watchlist.id, "user_id": watchlist.user_id,
        "name": watchlist.name, "sort_order": watchlist.sort_order,
        "created_at": watchlist.created_at.isoformat() if watchlist.created_at else None,
        "items": [],
    }


@router.post("/{watchlist_id}/items")
async def add_to_watchlist(
    watchlist_id: int,
    body: AddItemRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """添加股票到自选股（支持 stock_id 或 symbol）"""
    wl = db.query(Watchlist).filter(Watchlist.id == watchlist_id).first()
    if not wl:
        raise_not_found("自选股分组")
    if wl.user_id != current_user.id:
        raise_not_found("自选股分组")

    stock = None
    if body.stock_id:
        stock = db.query(Stock).filter(Stock.id == body.stock_id).first()
    elif body.symbol:
        stock = _ensure_stock_for_symbol(db, body)

    if not stock:
        raise_not_found("股票，请检查代码是否正确，或联系管理员导入数据")

    existing = db.query(WatchlistItem).filter(
        WatchlistItem.watchlist_id == watchlist_id,
        WatchlistItem.stock_id == stock.id,
    ).first()
    if existing:
        raise_bad_request("该股票已在自选股中")

    max_sort = (
        db.query(WatchlistItem.sort_order)
        .filter(WatchlistItem.watchlist_id == watchlist_id)
        .order_by(WatchlistItem.sort_order.desc())
        .first()
    )
    next_sort_order = ((max_sort[0] if max_sort else -1) or 0) + 1
    item = WatchlistItem(watchlist_id=watchlist_id, stock_id=stock.id, sort_order=next_sort_order)
    db.add(item)
    db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "stock_id": item.stock_id,
        "symbol": _api_symbol(stock),
        "name": _stock_display_name(stock),
        "market": stock.market,
        "sort_order": item.sort_order,
        "added_at": item.added_at.isoformat() if item.added_at else None,
    }


@router.post("/{watchlist_id}/items/batch")
async def batch_add_to_watchlist(
    watchlist_id: int,
    body: BatchAddRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批量添加股票到自选股"""
    wl = db.query(Watchlist).filter(Watchlist.id == watchlist_id).first()
    if not wl or wl.user_id != current_user.id:
        raise_not_found("自选股分组")

    existing_stock_ids = {
        item.stock_id
        for item in db.query(WatchlistItem).filter(WatchlistItem.watchlist_id == watchlist_id).all()
    }
    max_sort_row = (
        db.query(WatchlistItem.sort_order)
        .filter(WatchlistItem.watchlist_id == watchlist_id)
        .order_by(WatchlistItem.sort_order.desc())
        .first()
    )
    next_sort = ((max_sort_row[0] if max_sort_row else -1) or 0) + 1

    added = 0
    skipped = 0
    for symbol in body.symbols[:200]:
        code = _normalize_stock_code(symbol)
        if not code:
            skipped += 1
            continue
        try:
            stock = _ensure_stock_for_symbol(db, AddItemRequest(symbol=code))
        except Exception:
            skipped += 1
            continue
        if stock.id in existing_stock_ids:
            skipped += 1
            continue
        db.add(WatchlistItem(watchlist_id=watchlist_id, stock_id=stock.id, sort_order=next_sort))
        existing_stock_ids.add(stock.id)
        next_sort += 1
        added += 1

    db.commit()
    return {"added": added, "skipped": skipped}


@router.put("/{watchlist_id}/items/reorder")
async def reorder_watchlist_items(
    watchlist_id: int,
    body: ReorderItemsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按 stock_id 顺序重排自选股"""
    wl = db.query(Watchlist).filter(Watchlist.id == watchlist_id).first()
    if not wl or wl.user_id != current_user.id:
        raise_not_found("自选股分组")

    items = db.query(WatchlistItem).filter(WatchlistItem.watchlist_id == watchlist_id).all()
    item_by_stock_id = {item.stock_id: item for item in items}
    ordered_ids = []
    seen = set()
    for stock_id in body.stock_ids:
        if stock_id in item_by_stock_id and stock_id not in seen:
            ordered_ids.append(stock_id)
            seen.add(stock_id)
    ordered_ids.extend(item.stock_id for item in items if item.stock_id not in seen)

    for index, stock_id in enumerate(ordered_ids):
        item_by_stock_id[stock_id].sort_order = index
    db.commit()
    return {"message": "排序已更新", "stock_ids": ordered_ids}


@router.delete("/{watchlist_id}/items/{stock_id}")
async def remove_from_watchlist(
    watchlist_id: int,
    stock_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """从自选股移除"""
    wl = db.query(Watchlist).filter(Watchlist.id == watchlist_id).first()
    if not wl or wl.user_id != current_user.id:
        raise_not_found("自选股分组")

    item = db.query(WatchlistItem).filter(
        WatchlistItem.watchlist_id == watchlist_id,
        WatchlistItem.stock_id == stock_id,
    ).first()
    if not item:
        raise_not_found("自选股记录")
    db.delete(item)
    db.commit()
    return {"message": "移除成功"}
