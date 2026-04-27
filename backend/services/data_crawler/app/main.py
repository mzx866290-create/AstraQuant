"""
数据采集服务 v2 - 多源A股数据采集
集成东方财富/AKShare/Tushare + 故障降级链
"""
import logging
import sys
import os
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import atexit

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
sys.path.insert(0, _PROJECT_ROOT)

from backend.services.data_crawler.sources import (
    EastMoneySource, AKShareSource, TushareSource,
    DataSourceChain,
)
from backend.services.data_crawler.sources.news_source import create_news_chain
from backend.services.data_crawler.pipeline.etl import KLineETL
from backend.services.data_crawler.pipeline.financial_etl import AnnouncementETL, FinancialReportETL
from backend.services.data_crawler.pipeline.news_etl import NewsETL

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class DataCrawler:
    """多源A股数据采集器"""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.source_chain = DataSourceChain()
        self.news_chain = create_news_chain()
        self.etl = KLineETL()
        self.announcement_etl = AnnouncementETL()
        self.financial_etl = FinancialReportETL()
        self.news_etl = NewsETL()
        self._init_sources()

    def _init_sources(self):
        """初始化数据源链"""
        # 主源: 东方财富 (免费, 最快)
        eastmoney = EastMoneySource()

        # 备用1: AKShare (免费开源, 覆盖广)
        akshare = AKShareSource()

        # 备用2: Tushare (付费, 数据规范)
        tushare_token = os.getenv("TUSHARE_TOKEN", "")
        tushare = TushareSource(token=tushare_token)

        self.source_chain.register_many(eastmoney, akshare, tushare)
        logger.info(f"数据源链初始化完成: {[s.name for s in self.source_chain._sources]}")

    def start(self):
        """启动定时采集任务"""
        logger.info("数据采集服务启动...")

        # ── 定时任务 ──

        # 1. 工作日收盘后采集日K (15:30)
        self.scheduler.add_job(
            self.collect_daily_kline_for_all,
            "cron",
            day_of_week="0-4",
            hour=15,
            minute=30,
            id="collect_daily_kline",
        )

        # 2. 盘中每5分钟采集活跃股行情 (09:30-15:00)
        self.scheduler.add_job(
            self.collect_realtime_quotes,
            "cron",
            day_of_week="0-4",
            hour="9-14",
            minute="*/5",
            id="collect_realtime_quotes",
        )

        # 3. 每周一采集周K
        self.scheduler.add_job(
            self.collect_weekly_kline,
            "cron",
            day_of_week=0,
            hour=21,
            minute=0,
            id="collect_weekly_kline",
        )

        # 4. 每月1日采集月K
        self.scheduler.add_job(
            self.collect_monthly_kline,
            "cron",
            day=1,
            hour=21,
            minute=0,
            id="collect_monthly_kline",
        )

        # 5. 收盘后采集资金流向 (15:35)
        self.scheduler.add_job(
            self.collect_money_flow,
            "cron",
            day_of_week="0-4",
            hour=15,
            minute=35,
            id="collect_money_flow",
        )

        # 6. 盘后采集龙虎榜 (16:00)
        self.scheduler.add_job(
            self.collect_dragon_tiger,
            "cron",
            day_of_week="0-4",
            hour=16,
            minute=0,
            id="collect_dragon_tiger",
        )

        # 7. 盘中每5分钟采集个股实时新闻 (09:30-15:00)
        self.scheduler.add_job(
            self.collect_stock_news,
            "cron",
            day_of_week="0-4",
            hour="9-14",
            minute="*/5",
            id="collect_stock_news",
        )

        # 8. 盘后采集新闻汇总 (15:30)
        self.scheduler.add_job(
            self.collect_stock_news_close,
            "cron",
            day_of_week="0-4",
            hour=15,
            minute=30,
            id="collect_stock_news_close",
        )

        # 9. 盘后采集公告 (16:30)
        self.scheduler.add_job(
            self.collect_announcements,
            "cron",
            day_of_week="0-4",
            hour=16,
            minute=30,
            id="collect_announcements",
        )

        # 10. 每月1-5日凌晨采集财报
        self.scheduler.add_job(
            self.collect_financial_reports,
            "cron",
            day="1-5",
            hour=2,
            minute=7,
            id="collect_financial_reports",
        )

        self.scheduler.start()
        logger.info("定时任务已注册 (日K/实时/周K/月K/资金流向/龙虎榜/新闻/公告/财报)")

        atexit.register(self.shutdown)

    # ── 采集任务实现 ──

    async def collect_daily_kline_for_all(self):
        """采集全部关注股票的日K线"""
        logger.info(f"[{datetime.now()}] 开始批量采集日K数据...")
        # TODO: 从DB获取关注股票列表
        symbols = [
            "600519", "000858", "000651", "600036",
            "601398", "000333", "601888", "603259",
        ]
        success = 0
        for symbol in symbols:
            try:
                result = await self.source_chain.fetch_daily_kline(symbol)
                data = result["data"]
                source = result["source"]
                await self.etl.save_daily_kline(symbol, data, source)
                success += 1
                logger.info(f"[{symbol}] 日K数据采集完成 ({len(data)}条, 来源:{source})")
            except Exception as e:
                logger.error(f"[{symbol}] 采集失败: {e}")
        logger.info(f"批量采集完成: {success}/{len(symbols)} 成功")

    async def collect_realtime_quotes(self):
        """采集活跃A股实时行情"""
        logger.info(f"[{datetime.now()}] 采集实时行情...")
        # TODO: 实现
        pass

    async def collect_weekly_kline(self):
        """采集周K线"""
        logger.info(f"[{datetime.now()}] 采集周K数据...")
        # TODO: 实现
        pass

    async def collect_monthly_kline(self):
        """采集月K线"""
        logger.info(f"[{datetime.now()}] 采集月K数据...")
        # TODO: 实现
        pass

    async def collect_money_flow(self):
        """采集资金流向数据"""
        logger.info(f"[{datetime.now()}] 采集资金流向...")
        # TODO: 实现
        pass

    async def collect_dragon_tiger(self):
        """采集龙虎榜数据"""
        logger.info(f"[{datetime.now()}] 采集龙虎榜...")
        # TODO: 实现
        pass

    async def collect_stock_news(self):
        """盘中每5分钟采集个股实时新闻"""
        logger.info(f"[{datetime.now()}] 盘中采集个股新闻...")
        from backend.shared.database import SessionLocal

        symbols = self._get_tracked_symbols()
        db = SessionLocal()
        try:
            success = 0
            for symbol in symbols:
                try:
                    news = await self.news_chain.fetch_stock_news(symbol, limit=10)
                    if news:
                        await self.news_etl.save(db, symbol, news)
                        success += 1
                except Exception as e:
                    logger.debug(f"[{symbol}] 新闻采集失败: {e}")
            logger.info(f"盘中新闻采集完成: {success}/{len(symbols)} 成功")
        finally:
            db.close()

    async def collect_stock_news_close(self):
        """盘后采集新闻汇总"""
        logger.info(f"[{datetime.now()}] 盘后新闻汇总采集...")
        from backend.shared.database import SessionLocal

        symbols = self._get_tracked_symbols()
        db = SessionLocal()
        try:
            success = 0
            for symbol in symbols:
                try:
                    news = await self.news_chain.fetch_stock_news(symbol, limit=30)
                    if news:
                        await self.news_etl.save(db, symbol, news)
                        success += 1
                except Exception as e:
                    logger.debug(f"[{symbol}] 盘后新闻采集失败: {e}")
            logger.info(f"盘后新闻汇总完成: {success}/{len(symbols)} 成功")
        finally:
            db.close()

    async def collect_announcements(self):
        """盘后采集公告"""
        logger.info(f"[{datetime.now()}] 盘后采集公告...")
        from backend.shared.database import SessionLocal

        symbols = self._get_tracked_symbols()
        db = SessionLocal()
        try:
            success = 0
            for symbol in symbols:
                try:
                    result = await self.source_chain.fetch_with_fallback(
                        "fetch_stock_notices", symbol=symbol, limit=20
                    )
                    data = result["data"]
                    source = result["source"]
                    if data:
                        await self.announcement_etl.save(db, symbol, data, source)
                        success += 1
                        logger.info(f"[{symbol}] 公告采集完成 ({len(data)}条, 来源:{source})")
                except Exception as e:
                    logger.error(f"[{symbol}] 公告采集失败: {e}")
            logger.info(f"公告采集完成: {success}/{len(symbols)} 成功")
        finally:
            db.close()

    async def collect_financial_reports(self):
        """每月采集财报（资产负债表+利润表+现金流量表 → 衍生指标 → 入库）"""
        logger.info(f"[{datetime.now()}] 采集财报数据...")
        from backend.shared.database import SessionLocal

        symbols = self._get_tracked_symbols()
        db = SessionLocal()
        try:
            success = 0
            for symbol in symbols:
                try:
                    balance_result = await self.source_chain.fetch_with_fallback(
                        "fetch_balance_sheet", symbol=symbol
                    )
                    profit_result = await self.source_chain.fetch_with_fallback(
                        "fetch_profit_sheet", symbol=symbol
                    )
                    cashflow_result = await self.source_chain.fetch_with_fallback(
                        "fetch_cash_flow_sheet", symbol=symbol
                    )
                    source = balance_result["source"]
                    await self.financial_etl.save(
                        db, symbol,
                        balance_result["data"],
                        profit_result["data"],
                        cashflow_result["data"],
                        source,
                    )
                    success += 1
                    logger.info(f"[{symbol}] 财报采集完成 (来源:{source})")
                except Exception as e:
                    logger.error(f"[{symbol}] 财报采集失败: {e}")
            logger.info(f"财报采集完成: {success}/{len(symbols)} 成功")
        finally:
            db.close()

    def _get_tracked_symbols(self):
        """获取关注股票列表"""
        # TODO: 从DB获取关注股票列表
        return [
            "600519", "000858", "000651", "600036",
            "601398", "000333", "601888", "603259",
        ]

    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("数据采集服务已关闭")


if __name__ == "__main__":
    crawler = DataCrawler()
    crawler.start()
    try:
        import asyncio
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        logger.info("接收到终止信号，正在关闭...")
