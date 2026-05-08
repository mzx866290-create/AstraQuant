from __future__ import annotations

from datetime import datetime, timedelta
import logging
import os

from backend.shared.resilience import CircuitBreaker, CircuitBreakerOpenError

logger = logging.getLogger(__name__)

MONEY_FLOW_UNAVAILABLE_WARNING = "money_flow_not_implemented"
MONEY_FLOW_EMPTY_WARNING = "money_flow_empty"
MONEY_FLOW_SOURCE_ERROR_WARNING = "money_flow_source_error"
MONEY_FLOW_CIRCUIT_OPEN_WARNING = "money_flow_circuit_open"


def float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


DATA_SOURCE_BREAKER_RECOVERY_TIMEOUT = float_env("DATA_SOURCE_BREAKER_RECOVERY_TIMEOUT", 30.0)
kline_breakers = {
    "eastmoney": CircuitBreaker("scoring.kline.eastmoney", recovery_timeout=DATA_SOURCE_BREAKER_RECOVERY_TIMEOUT),
    "sina": CircuitBreaker("scoring.kline.sina", recovery_timeout=DATA_SOURCE_BREAKER_RECOVERY_TIMEOUT),
}
money_flow_breaker = CircuitBreaker(
    "scoring.money_flow.eastmoney",
    recovery_timeout=DATA_SOURCE_BREAKER_RECOVERY_TIMEOUT,
)


async def fetch_recent_kline(symbol: str, count: int = 200) -> list[dict]:
    """获取真实K线数据，东方财富不可用时降级到Sina/Tencent。"""
    errors = []
    for source_name in ("eastmoney", "sina"):
        try:
            async def fetch_from_source() -> list[dict]:
                if source_name == "eastmoney":
                    from backend.services.data_crawler.sources.eastmoney_source import EastMoneySource

                    source = EastMoneySource()
                    try:
                        return await source.fetch_daily_kline(symbol)
                    finally:
                        await source.close()

                from backend.services.data_crawler.sources.sina_tencent_source import SinaTencentSource

                return await SinaTencentSource().fetch_daily_kline(symbol)

            data = await kline_breakers[source_name].call(fetch_from_source)
            if data:
                return data[-count:] if len(data) > count else data
        except CircuitBreakerOpenError as exc:
            errors.append(f"{source_name}: circuit open")
            logger.debug("kline source %s circuit open for %s: %s", source_name, symbol, exc)
        except Exception as exc:
            errors.append(f"{source_name}: {exc}")
            logger.debug("kline source %s failed for %s: %s", source_name, symbol, exc)
    raise RuntimeError("; ".join(errors) or "no kline data")


def fetch_financial_reports(symbol: str) -> list[dict]:
    """从DB获取最近财报。"""
    from backend.shared.database import SessionLocal
    from backend.shared.models import FinancialReport

    code = symbol[:6]
    db = SessionLocal()
    try:
        rows = (
            db.query(FinancialReport)
            .filter(FinancialReport.stock_symbol == code)
            .order_by(FinancialReport.report_date.desc())
            .limit(8)
            .all()
        )
        return [
            {
                "report_date": row.report_date,
                "report_type": row.report_type,
                "revenue": row.revenue,
                "revenue_yoy": row.revenue_yoy,
                "net_profit": row.net_profit,
                "net_profit_yoy": row.net_profit_yoy,
                "gross_margin": row.gross_margin,
                "net_margin": row.net_margin,
                "operating_cf": row.operating_cf,
                "total_assets": row.total_assets,
                "total_liabilities": row.total_liabilities,
                "total_equity": row.total_equity,
                "roe": row.roe,
                "roa": row.roa,
                "pe_ttm": row.pe_ttm,
                "pb": row.pb,
            }
            for row in rows
        ]
    finally:
        db.close()


def fetch_recent_news(symbol: str, days: int = 7) -> list[dict]:
    """从DB获取近期新闻。"""
    from backend.shared.database import SessionLocal
    from backend.shared.models import StockNews

    code = symbol[:6]
    cutoff = datetime.now() - timedelta(days=days)
    db = SessionLocal()
    try:
        rows = (
            db.query(StockNews)
            .filter(StockNews.stock_symbol == code, StockNews.publish_time >= cutoff)
            .order_by(StockNews.publish_time.desc())
            .limit(100)
            .all()
        )
        return [
            {
                "title": row.title,
                "summary": row.summary,
                "source": row.source,
                "publish_time": row.publish_time,
                "sentiment": row.sentiment,
                "sentiment_score": row.sentiment_score,
                "impact_score": 8 if row.impact_level == "高" else 5 if row.impact_level == "中" else 2,
                "impact_level": row.impact_level,
                "event_category": row.event_category,
                "keywords": row.keywords or [],
            }
            for row in rows
        ]
    finally:
        db.close()


def build_money_flow_context(
    data: list[dict],
    source: str = "not_implemented",
    warning: str = MONEY_FLOW_UNAVAILABLE_WARNING,
    message: str = "资金流向数据暂未接入，情绪评分不包含资金流因子",
    confidence: float = 0.0,
) -> dict:
    if data:
        return {
            "data": data,
            "source": source,
            "status": "ok",
            "warnings": [],
            "data_quality": {
                "source": source,
                "status": "ok",
                "freshness": "latest_available",
                "confidence": 0.8,
                "warnings": [],
            },
        }

    return {
        "data": [],
        "source": source,
        "status": "unavailable",
        "warnings": [warning],
        "data_quality": {
            "source": source,
            "status": "unavailable",
            "freshness": "missing",
            "confidence": confidence,
            "warning": warning,
            "warnings": [warning],
            "message": message,
        },
    }


async def fetch_money_flow(symbol: str, days: int = 20) -> dict:
    """获取真实资金流向，失败时返回可信降级上下文。"""
    try:
        async def fetch_from_source() -> list[dict]:
            from backend.services.data_crawler.sources.eastmoney_source import EastMoneySource

            source = EastMoneySource()
            try:
                return await source.fetch_money_flow(symbol, limit=days)
            finally:
                await source.close()

        data = await money_flow_breaker.call(fetch_from_source)
    except CircuitBreakerOpenError as exc:
        logger.warning("[%s] money flow circuit open: %s", symbol, exc)
        return build_money_flow_context(
            [],
            source="eastmoney",
            warning=MONEY_FLOW_CIRCUIT_OPEN_WARNING,
            message=f"money flow data source temporarily unavailable: {exc}",
            confidence=0.0,
        )
    except Exception as exc:
        logger.warning("[%s] money flow source failed: %s", symbol, exc)
        return build_money_flow_context(
            [],
            source="eastmoney",
            warning=MONEY_FLOW_SOURCE_ERROR_WARNING,
            message=f"资金流向数据源异常，情绪评分不包含资金流因子: {exc}",
            confidence=0.0,
        )
    if not data:
        return build_money_flow_context(
            [],
            source="eastmoney",
            warning=MONEY_FLOW_EMPTY_WARNING,
            message="资金流向数据源暂未返回可用数据，情绪评分不包含资金流因子",
            confidence=0.05,
        )
    return build_money_flow_context(data, source="eastmoney")
