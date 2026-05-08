"""Data crawler service entry point."""
import atexit
import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
except Exception:  # pragma: no cover - exercised in dependency-light test envs
    class AsyncIOScheduler:  # type: ignore[no-redef]
        def __init__(self):
            self.running = False

        def add_job(self, *args, **kwargs):
            raise RuntimeError("apscheduler is required to run data crawler scheduled jobs")

        def get_jobs(self):
            return []

        def start(self):
            raise RuntimeError("apscheduler is required to run data crawler scheduled jobs")

        def shutdown(self):
            self.running = False

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
sys.path.insert(0, _PROJECT_ROOT)

from fastapi import FastAPI, Response  # noqa: E402

from backend.services.data_crawler.pipeline.crawl_status import (  # noqa: E402
    crawl_status_for_counts,
    now_utc,
    record_crawl_status,
)
from backend.services.data_crawler.pipeline.etl import (  # noqa: E402
    DragonTigerETL,
    KLineETL,
    MonthlyKLineETL,
    MoneyFlowETL,
    RealtimeQuoteETL,
    WeeklyKLineETL,
)
from backend.services.data_crawler.pipeline.financial_etl import (  # noqa: E402
    AnnouncementETL,
    FinancialReportETL,
)
from backend.services.data_crawler.pipeline.news_etl import NewsETL  # noqa: E402
from backend.services.data_crawler.sources import (  # noqa: E402
    AKShareSource,
    DataSourceChain,
    EastMoneySource,
    TushareSource,
)
from backend.services.data_crawler.sources.news_source import create_news_chain  # noqa: E402
from backend.shared.observability import (  # noqa: E402
    clickhouse_check,
    database_check,
    install_metrics,
    readiness_response,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


DEFAULT_TRACKED_SYMBOLS = [
    "600519",
    "000858",
    "000651",
    "600036",
    "601398",
    "000333",
    "601888",
    "603259",
]


CRAWLER_TASK_STATUSES = (
    "success",
    "partial",
    "empty",
    "no_saved",
    "error",
    "not_implemented",
    "empty_symbol_pool",
)
CRAWLER_TASK_RUNS_TOTAL = None
CRAWLER_TASK_ROWS_TOTAL = None
CRAWLER_TASK_LAST_RUN_TIMESTAMP = None
CRAWLER_TASK_LAST_SUCCESS_TIMESTAMP = None
CRAWLER_TASK_LAST_STATUS = None
CRAWLER_TASK_LAST_ROWS = None
CRAWLER_SCHEDULER_ENABLED = None
CRAWLER_SCHEDULER_RUNNING = None
CRAWLER_SCHEDULER_JOBS = None
CRAWLER_SCHEDULER_ERROR = None


def _existing_metric(name: str):
    try:
        from prometheus_client import REGISTRY
    except Exception:
        return None

    collectors = getattr(REGISTRY, "_names_to_collectors", {})
    for candidate in (name, f"{name}_total", f"{name}_created"):
        collector = collectors.get(candidate)
        if collector is not None:
            return collector
    return None


def _metric(name: str, factory):
    existing = _existing_metric(name)
    if existing is not None:
        return existing
    try:
        return factory()
    except ValueError:
        existing = _existing_metric(name)
        if existing is not None:
            return existing
        raise


def install_crawler_metrics() -> None:
    global CRAWLER_TASK_RUNS_TOTAL
    global CRAWLER_TASK_ROWS_TOTAL
    global CRAWLER_TASK_LAST_RUN_TIMESTAMP
    global CRAWLER_TASK_LAST_SUCCESS_TIMESTAMP
    global CRAWLER_TASK_LAST_STATUS
    global CRAWLER_TASK_LAST_ROWS
    global CRAWLER_SCHEDULER_ENABLED
    global CRAWLER_SCHEDULER_RUNNING
    global CRAWLER_SCHEDULER_JOBS
    global CRAWLER_SCHEDULER_ERROR

    try:
        from prometheus_client import Counter, Gauge
    except Exception as exc:
        logger.warning("prometheus_client unavailable, crawler metrics disabled: %s", exc)
        return

    if CRAWLER_TASK_RUNS_TOTAL is None:
        CRAWLER_TASK_RUNS_TOTAL = _metric(
            "stock_platform_data_crawler_task_runs",
            lambda: Counter(
                "stock_platform_data_crawler_task_runs",
                "Data crawler task runs grouped by task, final status, and source.",
                ("task", "status", "source"),
            ),
        )
    if CRAWLER_TASK_ROWS_TOTAL is None:
        CRAWLER_TASK_ROWS_TOTAL = _metric(
            "stock_platform_data_crawler_task_rows",
            lambda: Counter(
                "stock_platform_data_crawler_task_rows",
                "Rows fetched or saved by data crawler tasks.",
                ("task", "kind", "source"),
            ),
        )
    if CRAWLER_TASK_LAST_RUN_TIMESTAMP is None:
        CRAWLER_TASK_LAST_RUN_TIMESTAMP = _metric(
            "stock_platform_data_crawler_task_last_run_timestamp_seconds",
            lambda: Gauge(
                "stock_platform_data_crawler_task_last_run_timestamp_seconds",
                "Unix timestamp for the latest run of each data crawler task.",
                ("task",),
            ),
        )
    if CRAWLER_TASK_LAST_SUCCESS_TIMESTAMP is None:
        CRAWLER_TASK_LAST_SUCCESS_TIMESTAMP = _metric(
            "stock_platform_data_crawler_task_last_success_timestamp_seconds",
            lambda: Gauge(
                "stock_platform_data_crawler_task_last_success_timestamp_seconds",
                "Unix timestamp for the latest successful run of each data crawler task.",
                ("task",),
            ),
        )
    if CRAWLER_TASK_LAST_STATUS is None:
        CRAWLER_TASK_LAST_STATUS = _metric(
            "stock_platform_data_crawler_task_last_status",
            lambda: Gauge(
                "stock_platform_data_crawler_task_last_status",
                "One-hot status marker for the latest run of each data crawler task.",
                ("task", "status"),
            ),
        )
    if CRAWLER_TASK_LAST_ROWS is None:
        CRAWLER_TASK_LAST_ROWS = _metric(
            "stock_platform_data_crawler_task_last_rows",
            lambda: Gauge(
                "stock_platform_data_crawler_task_last_rows",
                "Rows fetched or saved by the latest run of each data crawler task.",
                ("task", "kind"),
            ),
        )
    if CRAWLER_SCHEDULER_ENABLED is None:
        CRAWLER_SCHEDULER_ENABLED = _metric(
            "stock_platform_data_crawler_scheduler_enabled",
            lambda: Gauge(
                "stock_platform_data_crawler_scheduler_enabled",
                "Whether the data crawler scheduler is configured to run.",
                ("service",),
            ),
        )
    if CRAWLER_SCHEDULER_RUNNING is None:
        CRAWLER_SCHEDULER_RUNNING = _metric(
            "stock_platform_data_crawler_scheduler_running",
            lambda: Gauge(
                "stock_platform_data_crawler_scheduler_running",
                "Whether the data crawler scheduler is currently running.",
                ("service",),
            ),
        )
    if CRAWLER_SCHEDULER_JOBS is None:
        CRAWLER_SCHEDULER_JOBS = _metric(
            "stock_platform_data_crawler_scheduler_jobs",
            lambda: Gauge(
                "stock_platform_data_crawler_scheduler_jobs",
                "Number of jobs registered in the data crawler scheduler.",
                ("service",),
            ),
        )
    if CRAWLER_SCHEDULER_ERROR is None:
        CRAWLER_SCHEDULER_ERROR = _metric(
            "stock_platform_data_crawler_scheduler_error",
            lambda: Gauge(
                "stock_platform_data_crawler_scheduler_error",
                "Whether the data crawler scheduler currently has an error.",
                ("service",),
            ),
        )


def observe_crawler_task(
    task_name: str,
    status: str,
    *,
    source: str | None = None,
    fetched: int | None = None,
    saved: int | None = None,
) -> None:
    install_crawler_metrics()
    if CRAWLER_TASK_RUNS_TOTAL is None:
        return

    source_label = source or "unknown"
    timestamp = datetime.now(timezone.utc).timestamp()
    CRAWLER_TASK_RUNS_TOTAL.labels(task=task_name, status=status, source=source_label).inc()
    CRAWLER_TASK_LAST_RUN_TIMESTAMP.labels(task=task_name).set(timestamp)
    if status == "success":
        CRAWLER_TASK_LAST_SUCCESS_TIMESTAMP.labels(task=task_name).set(timestamp)

    statuses = set(CRAWLER_TASK_STATUSES)
    statuses.add(status)
    for known_status in statuses:
        CRAWLER_TASK_LAST_STATUS.labels(task=task_name, status=known_status).set(1 if known_status == status else 0)

    if fetched is not None:
        fetched_count = max(int(fetched), 0)
        CRAWLER_TASK_ROWS_TOTAL.labels(task=task_name, kind="fetched", source=source_label).inc(fetched_count)
        CRAWLER_TASK_LAST_ROWS.labels(task=task_name, kind="fetched").set(fetched_count)
    if saved is not None:
        saved_count = max(int(saved), 0)
        CRAWLER_TASK_ROWS_TOTAL.labels(task=task_name, kind="saved", source=source_label).inc(saved_count)
        CRAWLER_TASK_LAST_ROWS.labels(task=task_name, kind="saved").set(saved_count)


def observe_scheduler_state(runtime, scheduler_running: bool) -> None:
    install_crawler_metrics()
    if CRAWLER_SCHEDULER_ENABLED is None:
        return

    CRAWLER_SCHEDULER_ENABLED.labels(service="data-crawler").set(1 if runtime.scheduler_enabled else 0)
    CRAWLER_SCHEDULER_RUNNING.labels(service="data-crawler").set(1 if scheduler_running else 0)
    CRAWLER_SCHEDULER_JOBS.labels(service="data-crawler").set(max(int(runtime.jobs_count or 0), 0))
    CRAWLER_SCHEDULER_ERROR.labels(service="data-crawler").set(1 if runtime.scheduler_error else 0)


class CrawlerRuntimeState:
    """In-process status snapshot used by health checks and metrics."""

    def __init__(self):
        self.started_at: str | None = None
        self.scheduler_enabled = True
        self.scheduler_error: str | None = None
        self.jobs_count = 0
        self.last_tasks: dict[str, dict] = {}

    def mark_started(self, jobs_count: int) -> None:
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.scheduler_enabled = True
        self.scheduler_error = None
        self.jobs_count = jobs_count

    def mark_disabled(self) -> None:
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.scheduler_enabled = False
        self.scheduler_error = "scheduler disabled by DATA_CRAWLER_ENABLE_SCHEDULER"
        self.jobs_count = 0

    def mark_error(self, exc: Exception) -> None:
        self.scheduler_error = str(exc)[:180]

    def record_task(
        self,
        task_name: str,
        status: str,
        *,
        symbol: str = "GLOBAL",
        source: str | None = None,
        fetched: int | None = None,
        saved: int | None = None,
        error_message: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        previous = self.last_tasks.get(task_name, {})
        item = {
            **previous,
            "task": task_name,
            "status": status,
            "symbol": symbol,
            "source": source,
            "fetched": fetched,
            "saved": saved,
            "error_message": (error_message or "")[:180],
            "last_run_at": now,
        }
        if status == "success":
            item["last_success_at"] = now
        self.last_tasks[task_name] = item

    def snapshot(self, scheduler_running: bool) -> dict:
        return {
            "service": "data-crawler",
            "started_at": self.started_at,
            "scheduler_enabled": self.scheduler_enabled,
            "scheduler_running": scheduler_running,
            "scheduler_error": self.scheduler_error,
            "jobs_count": self.jobs_count,
            "last_tasks": sorted(self.last_tasks.values(), key=lambda item: item["task"]),
        }


def scheduler_enabled() -> bool:
    return os.getenv("DATA_CRAWLER_ENABLE_SCHEDULER", "true").strip().lower() not in {"0", "false", "no"}


class DataCrawler:
    """Multi-source A-share data crawler."""

    def __init__(self):
        self.runtime = CrawlerRuntimeState()
        self.scheduler = AsyncIOScheduler()
        self.source_chain = DataSourceChain()
        self.news_chain = create_news_chain()
        self.etl = KLineETL()
        self.dragon_tiger_etl = DragonTigerETL()
        self.money_flow_etl = MoneyFlowETL()
        self.realtime_quote_etl = RealtimeQuoteETL()
        self.minute_etl = self.realtime_quote_etl
        self.weekly_etl = WeeklyKLineETL()
        self.monthly_etl = MonthlyKLineETL()
        self.announcement_etl = AnnouncementETL()
        self.financial_etl = FinancialReportETL()
        self.news_etl = NewsETL()
        self._init_sources()

    def _init_sources(self):
        eastmoney = EastMoneySource()
        akshare = AKShareSource()
        tushare = TushareSource(token=os.getenv("TUSHARE_TOKEN", ""))
        self.source_chain.register_many(eastmoney, akshare, tushare)
        logger.info("data source chain initialized: %s", [s.name for s in self.source_chain._sources])

    def start(self):
        if self.scheduler.running:
            return
        logger.info("data crawler service starting")
        try:
            from backend.shared.database import init_db

            init_db()
        except Exception as exc:
            logger.warning("database initialization skipped: %s", exc)

        self.scheduler.add_job(
            self.collect_daily_kline_for_all,
            "cron",
            day_of_week="0-4",
            hour=15,
            minute=30,
            id="collect_daily_kline",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.collect_realtime_quotes,
            "cron",
            day_of_week="0-4",
            hour="9-14",
            minute="*/5",
            id="collect_realtime_quotes",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.collect_weekly_kline,
            "cron",
            day_of_week=0,
            hour=21,
            minute=0,
            id="collect_weekly_kline",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.collect_monthly_kline,
            "cron",
            day=1,
            hour=21,
            minute=0,
            id="collect_monthly_kline",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.collect_money_flow,
            "cron",
            day_of_week="0-4",
            hour=15,
            minute=35,
            id="collect_money_flow",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.collect_dragon_tiger,
            "cron",
            day_of_week="0-4",
            hour=16,
            minute=0,
            id="collect_dragon_tiger",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.collect_stock_news,
            "cron",
            day_of_week="0-4",
            hour="9-14",
            minute="*/5",
            id="collect_stock_news",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.collect_stock_news_close,
            "cron",
            day_of_week="0-4",
            hour=15,
            minute=30,
            id="collect_stock_news_close",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.collect_announcements,
            "cron",
            day_of_week="0-4",
            hour=16,
            minute=30,
            id="collect_announcements",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.collect_financial_reports,
            "cron",
            day="1-5",
            hour=2,
            minute=7,
            id="collect_financial_reports",
            replace_existing=True,
        )

        try:
            self.scheduler.start()
        except Exception as exc:
            self.runtime.mark_error(exc)
            observe_scheduler_state(self.runtime, self.scheduler.running)
            raise
        self.runtime.mark_started(len(self.scheduler.get_jobs()))
        observe_scheduler_state(self.runtime, self.scheduler.running)
        logger.info("scheduled data crawler jobs registered")
        atexit.register(self.shutdown)

    async def collect_daily_kline_for_all(self):
        logger.info("[%s] collecting daily K-line data", datetime.now())
        symbols = self._get_tracked_symbols()
        if not symbols:
            return self._mark_empty_symbol_pool("daily_kline")
        target_date = self._daily_kline_target_date()
        success = 0
        for symbol in symbols:
            started_at = now_utc()
            try:
                result = await self.source_chain.fetch_daily_kline(
                    symbol,
                    start_date=target_date,
                    end_date=target_date,
                )
                data = self._filter_kline_rows_for_date(result["data"], target_date)
                source = result["source"]
                saved = await self.etl.save_daily_kline(symbol, data, source)
                status = crawl_status_for_counts(len(data), saved)
                self._record_status(
                    symbol,
                    "daily_kline",
                    status,
                    started_at,
                    source=source,
                    fetched=len(data),
                    saved=saved,
                )
                if status == "success":
                    success += 1
                logger.info(
                    "[%s] daily K-line collected: target=%s fetched=%s saved=%s status=%s source=%s",
                    symbol,
                    target_date,
                    len(data),
                    saved,
                    status,
                    source,
                )
            except Exception as exc:
                self._record_status(symbol, "daily_kline", "error", started_at, error_message=str(exc))
                logger.error("[%s] daily K-line collection failed: %s", symbol, exc)
        logger.info("daily K-line batch finished: %s/%s succeeded", success, len(symbols))
        return {"task": "daily_kline", "target_date": target_date, "success": success, "total": len(symbols)}

    async def collect_realtime_quotes(self):
        logger.info("[%s] collecting realtime minute snapshots", datetime.now())
        symbols = self._get_tracked_symbols()
        if not symbols:
            return self._mark_empty_symbol_pool("realtime_quotes")
        success = 0
        for symbol in symbols:
            started_at = now_utc()
            try:
                rows, source = await self._fetch_realtime_rows(symbol)
                saved = await self.minute_etl.save(symbol, rows)
                status = crawl_status_for_counts(len(rows), saved)
                self._record_status(
                    symbol,
                    "realtime_quotes",
                    status,
                    started_at,
                    source=source,
                    fetched=len(rows),
                    saved=saved,
                )
                if status == "success":
                    success += 1
                logger.info(
                    "[%s] realtime snapshot collected: fetched=%s saved=%s status=%s source=%s",
                    symbol,
                    len(rows),
                    saved,
                    status,
                    source,
                )
            except Exception as exc:
                self._record_status(symbol, "realtime_quotes", "error", started_at, error_message=str(exc))
                logger.error("[%s] realtime row collection failed: %s", symbol, exc)
        logger.info("realtime quote batch finished: %s/%s succeeded", success, len(symbols))
        return {"task": "realtime_quotes", "success": success, "total": len(symbols)}

    async def collect_weekly_kline(self):
        return await self._collect_period_kline("weekly_kline", "1w", self.weekly_etl)

    async def collect_monthly_kline(self):
        return await self._collect_period_kline("monthly_kline", "1M", self.monthly_etl)

    async def collect_money_flow(self):
        logger.info("[%s] collecting money flow data", datetime.now())
        symbols = self._get_tracked_symbols()
        if not symbols:
            return self._mark_empty_symbol_pool("money_flow")
        limit = self._money_flow_fetch_limit()
        success = 0
        for symbol in symbols:
            started_at = now_utc()
            try:
                result = await self.source_chain.fetch_with_fallback("fetch_money_flow", symbol=symbol, limit=limit)
                rows = result.get("data") or []
                source = result.get("source", "unknown")
                saved = await self.money_flow_etl.save(symbol, rows, source)
                status = crawl_status_for_counts(len(rows), saved)
                self._record_status(
                    symbol,
                    "money_flow",
                    status,
                    started_at,
                    source=source,
                    fetched=len(rows),
                    saved=saved,
                )
                if status == "success":
                    success += 1
                logger.info(
                    "[%s] money flow collected: fetched=%s saved=%s status=%s source=%s",
                    symbol,
                    len(rows),
                    saved,
                    status,
                    source,
                )
            except Exception as exc:
                self._record_status(symbol, "money_flow", "error", started_at, error_message=str(exc))
                logger.error("[%s] money flow collection failed: %s", symbol, exc)
        logger.info("money flow batch finished: %s/%s succeeded", success, len(symbols))
        return {"task": "money_flow", "success": success, "total": len(symbols), "limit": limit}

    async def collect_dragon_tiger(self):
        logger.info("[%s] collecting dragon tiger data", datetime.now())
        started_at = now_utc()
        target_date = os.getenv("DATA_CRAWLER_DRAGON_TIGER_DATE") or datetime.now().strftime("%Y-%m-%d")
        try:
            result = await self.source_chain.fetch_with_fallback("fetch_dragon_tiger", date=target_date)
            rows = result.get("data") or []
            source = result.get("source", "unknown")
            saved = await self.dragon_tiger_etl.save(rows, source)
            status = crawl_status_for_counts(len(rows), saved)
            self._record_status(
                "GLOBAL",
                "dragon_tiger",
                status,
                started_at,
                source=source,
                fetched=len(rows),
                saved=saved,
                error_message=None if status == "success" else f"dragon_tiger {status}",
            )
            logger.info(
                "dragon tiger collection finished: target=%s fetched=%s saved=%s status=%s source=%s",
                target_date,
                len(rows),
                saved,
                status,
                source,
            )
            return {
                "task": "dragon_tiger",
                "target_date": target_date,
                "status": status,
                "fetched": len(rows),
                "saved": saved,
                "source": source,
            }
        except Exception as exc:
            self._record_status("GLOBAL", "dragon_tiger", "error", started_at, error_message=str(exc))
            logger.error("dragon tiger collection failed: %s", exc)
            return {"task": "dragon_tiger", "target_date": target_date, "status": "error", "message": str(exc)}

    async def collect_stock_news(self):
        logger.info("[%s] collecting intraday stock news", datetime.now())
        return await self._collect_news(limit=10, task_name="stock_news")

    async def collect_stock_news_close(self):
        logger.info("[%s] collecting close stock news", datetime.now())
        return await self._collect_news(limit=30, task_name="stock_news_close")

    async def _collect_news(self, limit: int, task_name: str):
        from backend.shared.database import SessionLocal

        symbols = self._get_tracked_symbols()
        if not symbols:
            return self._mark_empty_symbol_pool(task_name)
        db = SessionLocal()
        try:
            success = 0
            for symbol in symbols:
                started_at = now_utc()
                try:
                    news = await self.news_chain.fetch_stock_news(symbol, limit=limit)
                    saved = await self.news_etl.save(db, symbol, news)
                    status = crawl_status_for_counts(len(news), saved)
                    self._record_status(
                        symbol,
                        "news",
                        status,
                        started_at,
                        source="multi-source-news",
                        fetched=len(news),
                        saved=saved,
                        metric_task_name=task_name,
                    )
                    if status == "success":
                        success += 1
                except Exception as exc:
                    db.rollback()
                    self._record_status(
                        symbol,
                        "news",
                        "error",
                        started_at,
                        error_message=str(exc),
                        metric_task_name=task_name,
                    )
                    logger.debug("[%s] news collection failed: %s", symbol, exc)
            logger.info("%s finished: %s/%s succeeded", task_name, success, len(symbols))
            return {"task": task_name, "success": success, "total": len(symbols)}
        finally:
            db.close()

    async def collect_announcements(self):
        logger.info("[%s] collecting announcements", datetime.now())
        from backend.shared.database import SessionLocal

        symbols = self._get_tracked_symbols()
        if not symbols:
            return self._mark_empty_symbol_pool("announcements")
        db = SessionLocal()
        try:
            success = 0
            for symbol in symbols:
                started_at = now_utc()
                try:
                    result = await self.source_chain.fetch_with_fallback("fetch_stock_notices", symbol=symbol, limit=20)
                    data = result["data"]
                    source = result["source"]
                    saved = await self.announcement_etl.save(db, symbol, data, source)
                    status = crawl_status_for_counts(len(data), saved)
                    self._record_status(
                        symbol,
                        "announcements",
                        status,
                        started_at,
                        source=source,
                        fetched=len(data),
                        saved=saved,
                    )
                    if status == "success":
                        success += 1
                    logger.info(
                        "[%s] announcements collected: fetched=%s saved=%s status=%s source=%s",
                        symbol,
                        len(data),
                        saved,
                        status,
                        source,
                    )
                except Exception as exc:
                    db.rollback()
                    self._record_status(symbol, "announcements", "error", started_at, error_message=str(exc))
                    logger.error("[%s] announcement collection failed: %s", symbol, exc)
            return {"task": "announcements", "success": success, "total": len(symbols)}
        finally:
            db.close()

    async def collect_financial_reports(self):
        logger.info("[%s] collecting financial reports", datetime.now())
        from backend.shared.database import SessionLocal

        symbols = self._get_tracked_symbols()
        if not symbols:
            return self._mark_empty_symbol_pool("financials")
        db = SessionLocal()
        try:
            success = 0
            for symbol in symbols:
                started_at = now_utc()
                try:
                    balance_result = await self.source_chain.fetch_with_fallback("fetch_balance_sheet", symbol=symbol)
                    profit_result = await self.source_chain.fetch_with_fallback("fetch_profit_sheet", symbol=symbol)
                    cashflow_result = await self.source_chain.fetch_with_fallback("fetch_cash_flow_sheet", symbol=symbol)
                    source = balance_result["source"]
                    saved = await self.financial_etl.save(
                        db,
                        symbol,
                        balance_result["data"],
                        profit_result["data"],
                        cashflow_result["data"],
                        source,
                    )
                    fetched = len(balance_result["data"]) + len(profit_result["data"]) + len(cashflow_result["data"])
                    status = crawl_status_for_counts(fetched, saved)
                    self._record_status(
                        symbol,
                        "financials",
                        status,
                        started_at,
                        source=source,
                        fetched=fetched,
                        saved=saved,
                    )
                    if status == "success":
                        success += 1
                    logger.info(
                        "[%s] financial reports collected: fetched=%s saved=%s status=%s source=%s",
                        symbol,
                        fetched,
                        saved,
                        status,
                        source,
                    )
                except Exception as exc:
                    db.rollback()
                    self._record_status(symbol, "financials", "error", started_at, error_message=str(exc))
                    logger.error("[%s] financial report collection failed: %s", symbol, exc)
            return {"task": "financials", "success": success, "total": len(symbols)}
        finally:
            db.close()

    def _daily_kline_target_date(self) -> str:
        configured = os.getenv("DATA_CRAWLER_DAILY_TARGET_DATE", "").strip()
        if configured:
            return configured[:10]
        return datetime.now().strftime("%Y-%m-%d")

    @staticmethod
    def _filter_kline_rows_for_date(rows: list[dict], target_date: str) -> list[dict]:
        return [
            row
            for row in rows
            if str(row.get("date", ""))[:10] == target_date
        ]

    async def _collect_period_kline(self, task_name: str, period: str, etl) -> dict:
        logger.info("[%s] collecting %s data", datetime.now(), task_name)
        symbols = self._get_tracked_symbols()
        if not symbols:
            return self._mark_empty_symbol_pool(task_name)
        success = 0
        for symbol in symbols:
            started_at = now_utc()
            try:
                rows, source = await self._fetch_period_rows(symbol, period)
                saved = await etl.save(symbol, rows, source)
                status = crawl_status_for_counts(len(rows), saved)
                self._record_status(
                    symbol,
                    task_name,
                    status,
                    started_at,
                    source=source,
                    fetched=len(rows),
                    saved=saved,
                )
                if status == "success":
                    success += 1
                logger.info(
                    "[%s] %s collected: fetched=%s saved=%s status=%s source=%s",
                    symbol,
                    task_name,
                    len(rows),
                    saved,
                    status,
                    source,
                )
            except Exception as exc:
                self._record_status(symbol, task_name, "error", started_at, error_message=str(exc))
                logger.error("[%s] %s collection failed: %s", symbol, task_name, exc)
        return {"task": task_name, "success": success, "total": len(symbols), "period": period}

    async def _fetch_period_rows(self, symbol: str, period: str) -> tuple[list[dict], str]:
        try:
            result = await self.source_chain.fetch_with_fallback(
                "fetch_kline",
                symbol=symbol,
                period=period,
                adjust="1",
                limit=1,
            )
            rows = result.get("data") or []
            if rows:
                return rows[-1:], result.get("source", "unknown")
        except Exception as exc:
            logger.debug("[%s] native %s kline fetch failed, trying daily aggregation: %s", symbol, period, exc)

        daily_result = await self.source_chain.fetch_daily_kline(symbol)
        aggregated = self._aggregate_period_rows(daily_result.get("data") or [], period)
        if aggregated:
            return aggregated[-1:], f"{daily_result.get('source', 'unknown')}-aggregated"
        return [], daily_result.get("source", "unknown")

    @staticmethod
    def _aggregate_period_rows(rows: list[dict], period: str) -> list[dict]:
        groups: dict[tuple[int, int], list[dict]] = {}
        for row in rows:
            raw_date = str(row.get("date", ""))[:10]
            if len(raw_date) != 10:
                continue
            row_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
            if period == "1w":
                iso = row_date.isocalendar()
                key = (iso.year, iso.week)
            else:
                key = (row_date.year, row_date.month)
            groups.setdefault(key, []).append(row)

        result = []
        for key in sorted(groups.keys()):
            items = sorted(groups[key], key=lambda item: str(item.get("date", "")))
            if not items:
                continue
            highs = [float(item.get("high", 0) or 0) for item in items]
            lows = [float(item.get("low", 0) or 0) for item in items]
            result.append({
                "date": str(items[-1].get("date", ""))[:10],
                "start_date": str(items[0].get("date", ""))[:10],
                "open": float(items[0].get("open", 0) or 0),
                "high": max(highs) if highs else 0.0,
                "low": min(lows) if lows else 0.0,
                "close": float(items[-1].get("close", 0) or 0),
                "volume": sum(int(float(item.get("volume", 0) or 0)) for item in items),
                "turnover": sum(float(item.get("turnover", 0) or 0) for item in items),
                "change_pct": float(items[-1].get("change_pct", 0) or 0),
                "amplitude": float(items[-1].get("amplitude", 0) or 0),
            })
        return result

    def _money_flow_fetch_limit(self) -> int:
        configured = os.getenv("DATA_CRAWLER_MONEY_FLOW_LIMIT", "").strip()
        if configured.isdigit():
            return max(1, min(int(configured), 60))
        return 20

    async def _fetch_realtime_rows(self, symbol: str) -> tuple[list[dict], str]:
        try:
            result = await self.source_chain.fetch_with_fallback(
                "fetch_kline",
                symbol=symbol,
                period="5m",
                adjust="1",
                limit=1,
            )
            rows = result.get("data") or []
            if rows:
                return rows[-1:], result.get("source", "unknown")
        except Exception as exc:
            logger.debug("[%s] 5m kline fetch failed, falling back to quote snapshot: %s", symbol, exc)

        from backend.services.data_crawler.sources.sina_tencent_source import SinaTencentSource

        quote = await SinaTencentSource().fetch_realtime_quote(symbol)
        return [self._build_snapshot_row(quote)], "tencent-snapshot"

    @staticmethod
    def _build_snapshot_row(quote: dict) -> dict:
        price = float(quote.get("price") or 0)
        if price <= 0:
            raise RuntimeError("quote snapshot price is unavailable")
        return {
            "timestamp": quote.get("timestamp") or datetime.now().isoformat(),
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 0,
            "turnover": 0.0,
            "trade_status": "SNAPSHOT",
        }

    def _get_tracked_symbols(self):
        try:
            from backend.shared.database import SessionLocal
            from backend.shared.models import Stock, WatchlistItem

            db = SessionLocal()
            try:
                rows = (
                    db.query(Stock.symbol)
                    .join(WatchlistItem, WatchlistItem.stock_id == Stock.id)
                    .filter(Stock.is_active.is_(True))
                    .distinct()
                    .all()
                )
                symbols = sorted({str(row[0])[:6] for row in rows if row[0]})
                if symbols:
                    return symbols
            finally:
                db.close()
        except Exception as exc:
            logger.warning("failed to load tracked symbols from watchlists: %s", exc)

        fallback = os.getenv("DATA_CRAWLER_FALLBACK_SYMBOLS", "")
        if fallback:
            symbols = [item.strip()[:6] for item in fallback.split(",") if item.strip()]
            if symbols:
                return symbols
        try:
            from backend.shared.config import is_production

            if is_production():
                logger.warning("no tracked symbols found; production crawler will not use default demo symbols")
                return []
        except Exception as exc:
            logger.warning("failed to evaluate production environment for tracked symbols: %s", exc)
        return list(DEFAULT_TRACKED_SYMBOLS)

    def _mark_task_not_implemented(self, task_name: str):
        started_at = now_utc()
        message = f"{task_name} collection is not implemented"
        self._record_status("GLOBAL", task_name[:30], "not_implemented", started_at, error_message=message)
        logger.warning("%s", message)
        return {"task": task_name, "status": "not_implemented", "message": message}

    def _mark_empty_symbol_pool(self, task_name: str):
        started_at = now_utc()
        message = f"{task_name} skipped because tracked symbol pool is empty"
        self._record_status("GLOBAL", task_name[:30], "empty_symbol_pool", started_at, error_message=message)
        logger.warning("%s", message)
        return {"task": task_name, "status": "empty_symbol_pool", "message": message, "success": 0, "total": 0}

    def _record_status(self, symbol: str, data_type: str, status: str, started_at, **kwargs):
        metric_task_name = kwargs.pop("metric_task_name", None) or data_type
        if hasattr(self, "runtime"):
            self.runtime.record_task(
                metric_task_name,
                status,
                symbol=symbol,
                source=kwargs.get("source"),
                fetched=kwargs.get("fetched"),
                saved=kwargs.get("saved"),
                error_message=kwargs.get("error_message"),
            )
        observe_crawler_task(
            metric_task_name,
            status,
            source=kwargs.get("source"),
            fetched=kwargs.get("fetched"),
            saved=kwargs.get("saved"),
        )
        try:
            from backend.shared.database import SessionLocal

            db = SessionLocal()
            try:
                return record_crawl_status(db, symbol, data_type, status, started_at, **kwargs)
            finally:
                db.close()
        except Exception as exc:
            logger.warning("failed to record crawl status for %s/%s: %s", symbol, data_type, exc)
            return None

    async def shutdown_async(self):
        if self.scheduler.running:
            self.scheduler.shutdown()
        for resource_name in ("source_chain", "news_chain"):
            resource = getattr(self, resource_name, None)
            close_fn = getattr(resource, "close", None)
            if not callable(close_fn):
                continue
            try:
                result = close_fn()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.warning("failed to close %s: %s", resource_name, exc)
        logger.info("data crawler service stopped")

    def shutdown(self):
        try:
            asyncio.run(self.shutdown_async())
        except RuntimeError as exc:
            logger.warning("data crawler async shutdown skipped: %s", exc)


crawler = DataCrawler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if scheduler_enabled():
        crawler.start()
    else:
        crawler.runtime.mark_disabled()
        observe_scheduler_state(crawler.runtime, crawler.scheduler.running)
        logger.warning("data crawler scheduler disabled by DATA_CRAWLER_ENABLE_SCHEDULER")
    try:
        yield
    finally:
        await crawler.shutdown_async()


app = FastAPI(
    title="Data Crawler Service",
    description="Scheduled A-share data collection service",
    version="1.0.0",
    lifespan=lifespan,
)
install_metrics(app, "data-crawler")
install_crawler_metrics()


@app.middleware("http")
async def crawler_metrics_refresh(request, call_next):
    if request.url.path == "/metrics":
        observe_scheduler_state(crawler.runtime, crawler.scheduler.running)
    return await call_next(request)


def scheduler_check() -> dict:
    observe_scheduler_state(crawler.runtime, crawler.scheduler.running)
    if not crawler.runtime.scheduler_enabled:
        return {
            "name": "scheduler",
            "status": "error",
            "required": True,
            "error": crawler.runtime.scheduler_error,
        }
    if crawler.scheduler.running:
        return {
            "name": "scheduler",
            "status": "ok",
            "required": True,
            "jobs_count": len(crawler.scheduler.get_jobs()),
        }
    return {
        "name": "scheduler",
        "status": "error",
        "required": True,
        "error": crawler.runtime.scheduler_error or "scheduler not running",
    }


@app.get("/health")
async def health_check():
    status = crawler.runtime.snapshot(crawler.scheduler.running)
    return {
        "status": "ok",
        **status,
    }


@app.get("/ready")
async def ready_check(response: Response):
    return readiness_response(
        "data-crawler",
        response,
        checks=[
            database_check,
            lambda: clickhouse_check(required=False),
            scheduler_check,
        ],
    )


@app.get("/status")
async def crawler_status():
    return crawler.runtime.snapshot(crawler.scheduler.running)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
