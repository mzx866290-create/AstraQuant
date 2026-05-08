"""
价格预警 API
基于PostgreSQL price_alerts表，支持价格突破/涨跌幅/成交量异动预警
"""
from fastapi import APIRouter, HTTPException, Depends, Request
from typing import List
from datetime import datetime
import logging

from backend.shared.audit import audit_log
from backend.shared.database import SessionLocal, get_db
from backend.shared.models import PriceAlert, Stock, User
from backend.shared.schemas import PriceAlertCreate, PriceAlertResponse
from backend.shared.auth import get_current_user, require_admin
from backend.shared.exceptions import raise_not_found, raise_bad_request
from backend.shared.rate_limit import enforce_rate_limit, user_identity
from backend.shared.resilience import CircuitBreaker, CircuitBreakerOpenError
from backend.services.market_service.app.api.v1.quotes import get_quote

router = APIRouter(prefix="/alerts", tags=["预警"])
logger = logging.getLogger(__name__)
quote_circuit_breaker = CircuitBreaker("alerts.quote")


def _api_symbol(stock: Stock | None) -> str | None:
    if not stock:
        return None
    code = stock.symbol[:6]
    return f"{code}.{stock.market}"


def _condition_met(alert: PriceAlert, quote: dict) -> tuple[bool, float | None, str]:
    if alert.alert_type in ("price_above", "price_below"):
        value = quote.get("price")
        label = "价格"
    else:
        value = quote.get("change_pct")
        label = "涨跌幅"

    try:
        current = float(value)
    except (TypeError, ValueError):
        return False, None, f"{label}不可用"

    threshold = float(alert.threshold)
    if alert.alert_type == "price_above":
        return current >= threshold, current, f"当前价格 {current:.2f}，阈值 >= {threshold:.2f}"
    if alert.alert_type == "price_below":
        return current <= threshold, current, f"当前价格 {current:.2f}，阈值 <= {threshold:.2f}"
    return abs(current) >= abs(threshold), current, f"当前涨跌幅 {current:.2f}%，阈值 ±{abs(threshold):.2f}%"


async def _check_one_alert(alert: PriceAlert, stock: Stock | None) -> dict:
    symbol = _api_symbol(stock)
    if not stock or not symbol:
        return {
            "alert_id": alert.id,
            "status": "error",
            "message": "股票不存在",
            "triggered": False,
        }

    try:
        quote = await quote_circuit_breaker.call(get_quote, symbol)
    except CircuitBreakerOpenError as exc:
        return {
            "alert_id": alert.id,
            "stock_symbol": symbol,
            "stock_name": stock.name,
            "status": "degraded",
            "message": f"quote data source temporarily unavailable: {exc}",
            "triggered": False,
            "degraded": True,
            "reason": "quote_circuit_open",
        }
    except Exception as exc:
        return {
            "alert_id": alert.id,
            "stock_symbol": symbol,
            "stock_name": stock.name,
            "status": "error",
            "message": f"行情获取失败: {str(exc)[:120]}",
            "triggered": False,
            "degraded": True,
            "reason": "quote_source_error",
        }

    matched, current_value, message = _condition_met(alert, quote)
    return {
        "alert_id": alert.id,
        "stock_symbol": symbol,
        "stock_name": stock.name,
        "alert_type": alert.alert_type,
        "threshold": alert.threshold,
        "current_value": current_value,
        "current_price": quote.get("price"),
        "current_change_pct": quote.get("change_pct"),
        "quote_source": quote.get("source"),
        "status": "triggered" if matched else "watching",
        "message": message,
        "triggered": matched,
    }


async def check_active_alerts(db, user_id: int | None = None, max_alerts: int = 200) -> dict:
    query = db.query(PriceAlert).filter(
        PriceAlert.is_active == True,
        PriceAlert.triggered_at.is_(None),
    )
    if user_id is not None:
        query = query.filter(PriceAlert.user_id == user_id)

    alerts = query.order_by(PriceAlert.created_at.desc()).limit(max_alerts).all()
    items = []
    now = datetime.now()
    for alert in alerts:
        stock = db.query(Stock).filter(Stock.id == alert.stock_id).first()
        item = await _check_one_alert(alert, stock)
        item["user_id"] = alert.user_id
        if item.get("triggered"):
            alert.triggered_at = now
            alert.is_active = False
        items.append(item)

    triggered_count = sum(1 for item in items if item.get("triggered"))
    if triggered_count:
        db.commit()

    return {
        "checked_count": len(items),
        "triggered_count": triggered_count,
        "items": items,
        "checked_at": now.isoformat(),
    }


async def check_all_active_alerts(max_alerts: int = 200) -> dict:
    db = SessionLocal()
    try:
        result = await check_active_alerts(db, user_id=None, max_alerts=max_alerts)
        if result["triggered_count"]:
            logger.info("auto alert check triggered %s alert(s)", result["triggered_count"])
        return result
    finally:
        db.close()


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
            user_id=alert.user_id,
            stock_id=alert.stock_id,
            alert_type=alert.alert_type,
            threshold=alert.threshold,
            is_active=alert.is_active,
            triggered_at=alert.triggered_at,
            created_at=alert.created_at,
            stock_symbol=_api_symbol(stock),
            stock_name=stock.name if stock else None,
        ))
    return result


@router.post("/check")
async def check_alerts(
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """检查当前用户所有启用中的预警，命中后自动触发并禁用"""
    await enforce_rate_limit(
        scope="alerts:check:user",
        identity=user_identity(current_user),
        limit=6,
        window_seconds=60,
        fail_closed=False,
    )
    return await check_active_alerts(db, user_id=current_user.id)


@router.get("/scheduler/status")
async def alert_scheduler_status(
    current_user: User = Depends(require_admin()),
):
    """查看预警自动检查任务状态"""
    from backend.services.market_service.app.tasks.alert_scheduler import alert_scheduler

    return alert_scheduler.status()


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
        user_id=alert.user_id,
        stock_id=alert.stock_id,
        alert_type=alert.alert_type,
        threshold=alert.threshold,
        is_active=alert.is_active,
        triggered_at=alert.triggered_at,
        created_at=alert.created_at,
        stock_symbol=_api_symbol(stock),
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
    request: Request,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """手动触发预警（测试用）"""
    alert = db.query(PriceAlert).filter(
        PriceAlert.id == alert_id,
        PriceAlert.user_id == current_user.id,
    ).first()
    if not alert:
        raise_not_found("预警规则")

    alert.triggered_at = datetime.now()
    alert.is_active = False
    audit_log(db, action="alert.manual_trigger", actor=current_user, request=request, target=f"alert:{alert_id}")
    db.commit()
    return {"message": "预警已触发并禁用"}
