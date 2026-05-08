"""Helpers for recording latest crawl outcomes."""
from datetime import datetime, timezone


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalize_symbol(symbol: str) -> str:
    return (symbol or "")[:6]


def crawl_status_for_counts(fetched: int, saved: int) -> str:
    if fetched <= 0:
        return "empty"
    if saved <= 0:
        return "no_saved"
    if saved < fetched:
        return "partial"
    return "success"


def record_crawl_status(
    db_session,
    symbol: str,
    data_type: str,
    status: str,
    started_at: datetime | None = None,
    *,
    source: str | None = None,
    fetched: int = 0,
    saved: int = 0,
    error_message: str | None = None,
):
    from backend.shared.models import CrawlStatus

    code = normalize_symbol(symbol)
    row = db_session.query(CrawlStatus).filter(
        CrawlStatus.stock_symbol == code,
        CrawlStatus.data_type == data_type,
    ).first()
    if row is None:
        row = CrawlStatus(stock_symbol=code, data_type=data_type)
        db_session.add(row)

    row.status = status
    row.source = source
    row.fetched_count = fetched
    row.saved_count = saved
    row.error_message = error_message[:2000] if error_message else None
    row.started_at = started_at or now_utc()
    row.finished_at = now_utc()
    db_session.commit()
    return row


def crawl_status_payload(row) -> dict:
    return {
        "status": row.status,
        "source": row.source,
        "fetched": row.fetched_count,
        "saved": row.saved_count,
        "error_message": row.error_message,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }
