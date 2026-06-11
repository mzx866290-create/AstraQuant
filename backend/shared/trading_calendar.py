"""A股交易日历：周一至周五且非法定节假日（调休补班的周末不开市）"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")


def now_cn() -> datetime:
    """当前北京时间（naive，便于与现有 datetime.now() 用法兼容）"""
    return datetime.now(CN_TZ).replace(tzinfo=None)

try:
    import chinese_calendar as _cc
except ImportError:
    _cc = None
    logger.warning("chinesecalendar not installed; trading-day check degrades to weekday-only")


def is_trading_day(d: date | datetime | None = None) -> bool:
    if d is None:
        d = now_cn()
    if isinstance(d, datetime):
        d = d.date()
    if d.weekday() >= 5:
        return False
    if _cc is None:
        return True
    try:
        return not _cc.is_holiday(d)
    except NotImplementedError:
        # 日期超出 chinesecalendar 支持范围（数据未更新到该年份）
        logger.warning("chinesecalendar has no data for %s; assuming trading day", d)
        return True


def next_trading_day(d: date | datetime | None = None) -> date:
    if d is None:
        d = now_cn()
    if isinstance(d, datetime):
        d = d.date()
    candidate = d + timedelta(days=1)
    while not is_trading_day(candidate):
        candidate += timedelta(days=1)
    return candidate
