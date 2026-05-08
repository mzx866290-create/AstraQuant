"""
自选股 API - 多分组管理
"""
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

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


def _api_symbol(stock: Stock) -> str:
    code = stock.symbol[:6]
    return f"{code}.{stock.market}"


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
        items = db.query(WatchlistItem).filter(WatchlistItem.watchlist_id == wl.id).all()
        item_data = []
        for item in items:
            stock = db.query(Stock).filter(Stock.id == item.stock_id).first()
            item_data.append({
                "id": item.id,
                "stock_id": item.stock_id,
                "symbol": _api_symbol(stock) if stock else "",
                "name": stock.name if stock else "",
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
        code = body.symbol[:6] if len(body.symbol) >= 6 else body.symbol
        stock = db.query(Stock).filter(Stock.symbol.like(f"{code}%")).first()

    if not stock:
        raise_not_found("股票，请检查代码是否正确，或联系管理员导入数据")

    existing = db.query(WatchlistItem).filter(
        WatchlistItem.watchlist_id == watchlist_id,
        WatchlistItem.stock_id == stock.id,
    ).first()
    if existing:
        raise_bad_request("该股票已在自选股中")

    item = WatchlistItem(watchlist_id=watchlist_id, stock_id=stock.id)
    db.add(item)
    db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "stock_id": item.stock_id,
        "symbol": _api_symbol(stock),
        "name": stock.name,
        "market": stock.market,
        "sort_order": item.sort_order,
        "added_at": item.added_at.isoformat() if item.added_at else None,
    }


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
