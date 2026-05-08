"""
按股票即时采集接口 — 用于详情页空状态一键补数据
"""
import logging

from fastapi import APIRouter, Depends, HTTPException

from backend.shared.auth import get_current_user, require_admin
from backend.shared.models import User
from backend.services.data_crawler.pipeline.crawl_status import (
    crawl_status_for_counts,
    crawl_status_payload,
    normalize_symbol,
    now_utc,
    record_crawl_status,
)

router = APIRouter(tags=["数据采集"])


logger = logging.getLogger(__name__)


def _save_crawl_status(db, symbol: str, data_type: str, status: str, started_at, **kwargs):
    try:
        return record_crawl_status(
            db,
            symbol,
            data_type,
            status,
            started_at,
            source=kwargs.get("source"),
            fetched=kwargs.get("fetched", 0),
            saved=kwargs.get("saved", 0),
            error_message=kwargs.get("error_message"),
        )
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        logger.warning("failed to record crawl status for %s/%s: %s", symbol, data_type, exc)
        return None


def _inline_status_payload(status: str, *, source=None, fetched: int = 0, saved: int = 0, error_message=None):
    timestamp = now_utc().isoformat()
    return {
        "status": status,
        "source": source,
        "fetched": fetched,
        "saved": saved,
        "error_message": str(error_message)[:2000] if error_message else None,
        "started_at": None,
        "finished_at": timestamp,
    }


def _status_payload(row, fallback=None):
    return crawl_status_payload(row) if row is not None else fallback


async def _close_if_available(resource):
    close_fn = getattr(resource, "close", None)
    if close_fn:
        await close_fn()


@router.get("/{symbol}/status")
async def get_crawl_status(
    symbol: str,
    current_user: User = Depends(get_current_user),
):
    """获取单只股票最近采集状态"""
    from backend.shared.database import SessionLocal
    from backend.shared.models import CrawlStatus

    code = normalize_symbol(symbol)
    db = SessionLocal()
    try:
        rows = db.query(CrawlStatus).filter(CrawlStatus.stock_symbol == code).all()
        statuses = {row.data_type: _status_payload(row) for row in rows}
        return {"symbol": code, "statuses": statuses}
    finally:
        db.close()


@router.post("/{symbol}/news")
async def crawl_stock_news(
    symbol: str,
    current_user: User = Depends(require_admin()),
):
    """即时采集单只股票新闻"""
    from backend.shared.database import SessionLocal
    from backend.services.data_crawler.sources.news_source import create_news_chain
    from backend.services.data_crawler.pipeline.news_etl import NewsETL

    code = normalize_symbol(symbol)
    started_at = now_utc()
    chain = create_news_chain()
    etl = NewsETL()
    db = SessionLocal()
    try:
        news = await chain.fetch_stock_news(code, limit=30)
        saved = await etl.save(db, code, news)
        status = crawl_status_for_counts(len(news), saved)
        status_row = _save_crawl_status(
            db, code, "news", status, started_at,
            source="多源新闻", fetched=len(news), saved=saved,
        )
        status_payload = _status_payload(
            status_row,
            _inline_status_payload(status, source="multi-source-news", fetched=len(news), saved=saved),
        )
        return {
            "symbol": code,
            "data_type": "news",
            "status": status,
            "fetched": len(news),
            "saved": saved,
            "updated_at": status_payload["finished_at"],
            "crawl_status": status_payload,
        }
    except Exception as e:
        db.rollback()
        _save_crawl_status(db, code, "news", "error", started_at, error_message=str(e))
        raise HTTPException(status_code=500, detail=f"新闻采集失败: {e}")
    finally:
        await chain.close()
        db.close()


@router.post("/{symbol}/announcements")
async def crawl_announcements(
    symbol: str,
    current_user: User = Depends(require_admin()),
):
    """即时采集单只股票公告"""
    from backend.shared.database import SessionLocal
    from backend.services.data_crawler.sources import AKShareSource
    from backend.services.data_crawler.pipeline.financial_etl import AnnouncementETL

    code = normalize_symbol(symbol)
    started_at = now_utc()
    source = AKShareSource()
    etl = AnnouncementETL()
    db = SessionLocal()
    try:
        data = await source.fetch_stock_notices(symbol=code, limit=30)
        saved = await etl.save(db, code, data, "CNINFO")
        status = crawl_status_for_counts(len(data), saved)
        status_row = _save_crawl_status(
            db, code, "announcements", status, started_at,
            source="CNINFO", fetched=len(data), saved=saved,
        )
        status_payload = _status_payload(
            status_row,
            _inline_status_payload(status, source="CNINFO", fetched=len(data), saved=saved),
        )
        return {
            "symbol": code,
            "data_type": "announcements",
            "status": status,
            "source": "CNINFO",
            "fetched": len(data),
            "saved": saved,
            "updated_at": status_payload["finished_at"],
            "crawl_status": status_payload,
        }
    except Exception as e:
        db.rollback()
        _save_crawl_status(db, code, "announcements", "error", started_at, error_message=str(e))
        raise HTTPException(status_code=500, detail=f"公告采集失败: {e}")
    finally:
        db.close()


@router.post("/{symbol}/financials")
async def crawl_financials(
    symbol: str,
    current_user: User = Depends(require_admin()),
):
    """即时采集单只股票财报"""
    from backend.shared.database import SessionLocal
    from backend.services.data_crawler.sources import AKShareSource
    from backend.services.data_crawler.pipeline.financial_etl import FinancialReportETL

    code = normalize_symbol(symbol)
    started_at = now_utc()
    source = AKShareSource()
    etl = FinancialReportETL()
    db = SessionLocal()
    try:
        balance = await source.fetch_balance_sheet(symbol=code)
        profit = await source.fetch_profit_sheet(symbol=code)
        cashflow = await source.fetch_cash_flow_sheet(symbol=code)
        fetched = len(balance) + len(profit) + len(cashflow)
        saved = await etl.save(
            db,
            code,
            balance,
            profit,
            cashflow,
            source.name,
        )
        status = crawl_status_for_counts(fetched, saved)
        status_row = _save_crawl_status(
            db, code, "financials", status, started_at,
            source=source.name, fetched=fetched, saved=saved,
        )
        status_payload = _status_payload(
            status_row,
            _inline_status_payload(status, source=source.name, fetched=fetched, saved=saved),
        )
        return {
            "symbol": code,
            "data_type": "financials",
            "status": status,
            "source": source.name,
            "fetched": fetched,
            "saved": saved,
            "updated_at": status_payload["finished_at"],
            "crawl_status": status_payload,
        }
    except Exception as e:
        db.rollback()
        _save_crawl_status(db, code, "financials", "error", started_at, error_message=str(e))
        raise HTTPException(status_code=500, detail=f"财报采集失败: {e}")
    finally:
        db.close()
