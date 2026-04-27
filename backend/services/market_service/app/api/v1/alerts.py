"""
价格预警 API
基于PostgreSQL price_alerts表，支持价格突破/涨跌幅/成交量异动预警
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import List
from datetime import datetime

from backend.shared.database import get_db
from backend.shared.models import PriceAlert, Stock, User
from backend.shared.schemas import PriceAlertCreate, PriceAlertResponse
from backend.shared.auth import get_current_user
from backend.shared.exceptions import raise_not_found, raise_bad_request

router = APIRouter(prefix="/alerts", tags=["预警"])


@router.get("", response_model=List[PriceAlertResponse])
async def get_alerts(
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """获取当前用户的预警规则列表"""
    alerts = db.query(PriceAlert).filter(
        PriceAlert.user_id == current_user.id
    ).order_by(PriceAlert.created_at.desc()).all()

    result = []
    for alert in alerts:
        stock = db.query(Stock).filter(Stock.id == alert.stock_id).first()
        result.append(PriceAlertResponse(
            id=alert.id,
            stock_id=alert.stock_id,
            alert_type=alert.alert_type,
            threshold=alert.threshold,
            is_active=alert.is_active,
            triggered_at=alert.triggered_at,
            created_at=alert.created_at,
            stock_symbol=stock.symbol if stock else None,
            stock_name=stock.name if stock else None,
        ))
    return result


@router.post("", response_model=PriceAlertResponse)
async def create_alert(
    data: PriceAlertCreate,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """创建价格预警规则"""
    # 验证股票是否存在
    stock = db.query(Stock).filter(Stock.id == data.stock_id).first()
    if not stock:
        raise_not_found("股票")

    # 验证预警类型
    valid_types = ["price_above", "price_below", "change_pct"]
    if data.alert_type not in valid_types:
        raise_bad_request(f"预警类型必须是: {', '.join(valid_types)}")

    alert = PriceAlert(
        user_id=current_user.id,
        stock_id=data.stock_id,
        alert_type=data.alert_type,
        threshold=data.threshold,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)

    return PriceAlertResponse(
        id=alert.id,
        stock_id=alert.stock_id,
        alert_type=alert.alert_type,
        threshold=alert.threshold,
        is_active=alert.is_active,
        triggered_at=alert.triggered_at,
        created_at=alert.created_at,
        stock_symbol=stock.symbol,
        stock_name=stock.name,
    )


@router.delete("/{alert_id}")
async def delete_alert(
    alert_id: int,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """删除预警规则"""
    alert = db.query(PriceAlert).filter(
        PriceAlert.id == alert_id,
        PriceAlert.user_id == current_user.id
    ).first()
    if not alert:
        raise_not_found("预警规则")

    db.delete(alert)
    db.commit()
    return {"message": "预警规则已删除"}


@router.put("/{alert_id}/toggle")
async def toggle_alert(
    alert_id: int,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """启用/禁用预警"""
    alert = db.query(PriceAlert).filter(
        PriceAlert.id == alert_id,
        PriceAlert.user_id == current_user.id
    ).first()
    if not alert:
        raise_not_found("预警规则")

    alert.is_active = not alert.is_active
    db.commit()
    return {"message": f"预警已{'启用' if alert.is_active else '禁用'}", "is_active": alert.is_active}


@router.post("/{alert_id}/trigger")
async def trigger_alert(
    alert_id: int,
    db=Depends(get_db),
):
    """手动触发预警（测试用）"""
    alert = db.query(PriceAlert).filter(PriceAlert.id == alert_id).first()
    if not alert:
        raise_not_found("预警规则")

    alert.triggered_at = datetime.now()
    alert.is_active = False
    db.commit()
    return {"message": "预警已触发并禁用"}
