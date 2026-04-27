"""
数据源抽象基类 - 所有A股数据源的统一接口
"""
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class SourceStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


class CircuitBreaker:
    """
    熔断器模式：连续失败N次后自动跳过该数据源一段时间
    避免对已故障的数据源反复重试
    """

    def __init__(self, failure_threshold: int = 3, recovery_timeout: int = 300):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout  # 秒
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.status = SourceStatus.HEALTHY

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        if self.failure_count >= self.failure_threshold:
            self.status = SourceStatus.DOWN
            logger.warning(
                f"熔断器触发: 连续{self.failure_count}次失败，暂停服务{self.recovery_timeout}秒"
            )

    def record_success(self):
        self.failure_count = 0
        self.status = SourceStatus.HEALTHY

    def is_available(self) -> bool:
        if self.status == SourceStatus.HEALTHY:
            return True
        if self.last_failure_time and (
            datetime.now() - self.last_failure_time
        ) > timedelta(seconds=self.recovery_timeout):
            self.status = SourceStatus.DEGRADED  # 半开状态，允许尝试
            return True
        return False


class BaseDataSource(ABC):
    """数据源抽象基类"""

    def __init__(self, name: str, priority: int):
        self.name = name
        self.priority = priority  # 数值越小优先级越高
        self.circuit_breaker = CircuitBreaker()

    @abstractmethod
    async def fetch_daily_kline(
        self, symbol: str, start_date: str = "", end_date: str = "", adjust: str = ""
    ) -> list[dict]:
        """获取日K线数据"""
        ...

    @abstractmethod
    async def fetch_realtime_quote(self, symbol: str) -> dict:
        """获取实时行情"""
        ...

    @abstractmethod
    async def search_stocks(self, query: str) -> list[dict]:
        """搜索股票"""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """健康检查"""
        ...

    def _validate_a_share_symbol(self, symbol: str) -> bool:
        """验证A股代码格式"""
        if not symbol or len(symbol) < 6:
            return False
        code = symbol[:6]
        # 沪市: 600, 601, 603, 605, 688(科创板)
        # 深市: 000, 001, 002, 003, 300(创业板)
        # 北交所: 430, 830, 870, 920
        # 支持纯数字代码或带后缀格式
        if code.isdigit():
            prefix = code[:3]
            valid_prefixes = [
                "600", "601", "603", "605", "688",  # 沪市
                "000", "001", "002", "003", "300",  # 深市
                "430", "830", "870", "920",          # 北交所
                "159", "510", "511", "512", "513", "515", "516", "517", "518", "588",  # ETF
            ]
            return prefix in valid_prefixes
        return False

    def _normalize_symbol(self, symbol: str) -> str:
        """标准化A股代码：统一转为纯数字代码"""
        return symbol[:6]

    def _get_market(self, symbol: str) -> str:
        """根据代码判断所属市场"""
        code = symbol[:3]
        if code in ("600", "601", "603", "605", "688"):
            return "SH"
        elif code in ("000", "001", "002", "003", "300"):
            return "SZ"
        elif code in ("430", "830", "870", "920"):
            return "BJ"
        return "OTHER"
