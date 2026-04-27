"""
数据源故障降级链管理器
自动按优先级尝试各数据源，失败自动切换下一个
支持熔断器跳过不可用源
"""
import asyncio
import logging
from typing import Callable

from .base import BaseDataSource

logger = logging.getLogger(__name__)


class DataSourceChain:
    """
    数据源降级链
    注册多个数据源，按优先级逐个尝试
    """

    def __init__(self):
        self._sources: list[BaseDataSource] = []

    def register(self, source: BaseDataSource):
        """注册数据源，按priority排序"""
        self._sources.append(source)
        self._sources.sort(key=lambda s: s.priority)
        logger.info(f"注册数据源: {source.name} (优先级: {source.priority})")

    def register_many(self, *sources: BaseDataSource):
        for s in sources:
            self.register(s)

    async def fetch_with_fallback(self, method_name: str, **kwargs) -> dict:
        """
        通用降级调用
        method_name: 方法名，如 'fetch_daily_kline'
        kwargs: 传给该方法的参数
        返回 {"data": ..., "source": "源名称"}
        """
        last_error = None
        for source in self._sources:
            if not source.circuit_breaker.is_available():
                logger.debug(f"跳过数据源 {source.name} (熔断中)")
                continue
            try:
                method: Callable = getattr(source, method_name)
                result = await asyncio.wait_for(method(**kwargs), timeout=15.0)
                source.circuit_breaker.record_success()
                logger.info(f"数据源 {source.name} 成功: {method_name}")
                return {"data": result, "source": source.name}
            except Exception as e:
                source.circuit_breaker.record_failure()
                logger.warning(f"数据源 {source.name} 失败 ({method_name}): {e}")
                last_error = e

        raise RuntimeError(
            f"所有数据源均不可用, 最后错误: {last_error}"
        )

    async def fetch_daily_kline(
        self, symbol: str, start_date: str = "", end_date: str = "", adjust: str = ""
    ) -> dict:
        return await self.fetch_with_fallback(
            "fetch_daily_kline",
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
        )

    async def fetch_realtime_quote(self, symbol: str) -> dict:
        return await self.fetch_with_fallback(
            "fetch_realtime_quote", symbol=symbol
        )

    async def search_stocks(self, query: str) -> dict:
        return await self.fetch_with_fallback(
            "search_stocks", query=query
        )
