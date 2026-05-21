"""多级缓存策略管理 (Redis可选，不可用时降级为内存缓存)"""
import json
from functools import wraps
from typing import Optional, Callable, Any
from datetime import datetime, timedelta
import logging
import os

logger = logging.getLogger(__name__)

# TTL策略
DEFAULT_CACHE_TTL = timedelta(minutes=10)
CACHE_TTL_REALTIME_QUOTE = timedelta(seconds=5)
CACHE_TTL_MINUTE_KLINE = timedelta(minutes=1)
CACHE_TTL_DAILY_KLINE = timedelta(hours=24)
CACHE_TTL_WEEK_MONTH_KLINE = timedelta(days=7)
CACHE_TTL_SEARCH_RESULT = timedelta(minutes=5)
CACHE_TTL_DAILY_RECOMMENDATIONS_MAX = timedelta(hours=24)

# Central cache TTL policy. Values are timedelta for fixed TTLs; dynamic
# categories are resolved by resolve_cache_ttl().
TTL_POLICY = {
    "realtime_quote": CACHE_TTL_REALTIME_QUOTE,
    "quote": CACHE_TTL_REALTIME_QUOTE,
    "market_quote": CACHE_TTL_REALTIME_QUOTE,
    "minute_kline": CACHE_TTL_MINUTE_KLINE,
    "intraday_kline": CACHE_TTL_MINUTE_KLINE,
    "daily_kline": CACHE_TTL_DAILY_KLINE,
    "weekly_kline": CACHE_TTL_WEEK_MONTH_KLINE,
    "monthly_kline": CACHE_TTL_WEEK_MONTH_KLINE,
    "week_month_kline": CACHE_TTL_WEEK_MONTH_KLINE,
    "stock_info": timedelta(hours=12),
    "financial_data": timedelta(days=1),
    "search_result": CACHE_TTL_SEARCH_RESULT,
    "search": CACHE_TTL_SEARCH_RESULT,
    "user_watchlist": timedelta(minutes=5),
    "ai_analysis_report": timedelta(hours=8),
    "ai_batch_summary": timedelta(hours=2),
    "ai_model_health": timedelta(hours=1),
    "daily_recommendations": CACHE_TTL_DAILY_RECOMMENDATIONS_MAX,
}

_INTRADAY_KLINE_PERIODS = {"1m", "5m", "15m", "30m", "60m"}
_WEEK_MONTH_KLINE_PERIODS = {"1w", "1M", "1mo", "month", "weekly", "monthly"}


def seconds(ttl: timedelta) -> int:
    return max(1, int(ttl.total_seconds()))


def ttl_until_next_day(now: Optional[datetime] = None) -> timedelta:
    current = now or datetime.now()
    next_day = (current + timedelta(days=1)).date()
    next_midnight = datetime.combine(next_day, datetime.min.time())
    ttl = next_midnight - current
    if ttl.total_seconds() <= 0:
        return CACHE_TTL_DAILY_RECOMMENDATIONS_MAX
    return min(ttl, CACHE_TTL_DAILY_RECOMMENDATIONS_MAX)


def resolve_cache_ttl(category: str, now: Optional[datetime] = None) -> timedelta:
    if category == "daily_recommendations":
        return ttl_until_next_day(now)
    return TTL_POLICY.get(category, DEFAULT_CACHE_TTL)


def cache_ttl_seconds(category: str, now: Optional[datetime] = None) -> int:
    return seconds(resolve_cache_ttl(category, now))


def cache_category_for_kline_period(period: str) -> str:
    normalized = str(period)
    if normalized in _INTRADAY_KLINE_PERIODS:
        return "minute_kline"
    if normalized == "1d":
        return "daily_kline"
    if normalized in _WEEK_MONTH_KLINE_PERIODS:
        return "week_month_kline"
    return "daily_kline"

redis_client: Optional[Any] = None
_redis_unavailable = False
_fallback_memory: dict = {}
_MEMORY_CACHE_MAX_SIZE = 2000


async def init_redis():
    """初始化Redis连接（不可用时静默降级）"""
    global redis_client, _redis_unavailable
    if _redis_unavailable:
        return
    try:
        import redis.asyncio as redis
        redis_client = await redis.from_url(
            f"redis://{os.getenv('REDIS_HOST', 'localhost')}:"
            f"{os.getenv('REDIS_PORT', '6379')}",
            encoding="utf8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        await redis_client.ping()
        logger.info("Redis连接已初始化")
    except Exception:
        _redis_unavailable = True
        redis_client = None
        logger.info("Redis不可用，使用内存缓存降级")


async def close_redis():
    """关闭Redis连接"""
    global redis_client
    if redis_client:
        try:
            await redis_client.close()
        except Exception:
            pass
        redis_client = None
        logger.info("Redis连接已关闭")


class CacheManager:
    """统一缓存管理器 (Redis可用时使用Redis，否则使用内存字典)"""

    def __init__(self, client=None):
        self.redis = client
        self._memory = _fallback_memory

    def _make_key(self, category: str, *args) -> str:
        raw = f"{category}:{'|'.join(str(a) for a in args)}"
        return f"stock:{raw}"

    async def get(self, category: str, *args) -> Optional[Any]:
        key = self._make_key(category, *args)
        if self.redis:
            try:
                data = await self.redis.get(key)
                if data:
                    return json.loads(data)
            except Exception:
                pass
        # 内存缓存降级
        entry = self._memory.get(key)
        if entry:
            import time
            if time.time() < entry["expires"]:
                return entry["value"]
            del self._memory[key]
        return None

    async def set(self, category: str, *args, value: Any, ttl: Optional[timedelta] = None):
        key = self._make_key(category, *args)
        effective_ttl = ttl or resolve_cache_ttl(category)
        if self.redis:
            try:
                await self.redis.setex(
                    key, seconds(effective_ttl), json.dumps(value, default=str)
                )
                return
            except Exception:
                pass
        # 内存缓存降级
        import time
        if len(self._memory) >= _MEMORY_CACHE_MAX_SIZE:
            now = time.time()
            expired_keys = [k for k, v in self._memory.items() if now >= v["expires"]]
            for k in expired_keys:
                del self._memory[k]
            if len(self._memory) >= _MEMORY_CACHE_MAX_SIZE:
                oldest_keys = sorted(self._memory, key=lambda k: self._memory[k]["expires"])[:len(self._memory) // 4]
                for k in oldest_keys:
                    del self._memory[k]
        self._memory[key] = {
            "value": value,
            "expires": time.time() + effective_ttl.total_seconds(),
        }

    async def invalidate(self, category: str, *args):
        key = self._make_key(category, *args)
        if self.redis:
            try:
                await self.redis.delete(key)
            except Exception:
                pass
        self._memory.pop(key, None)

    async def invalidate_pattern(self, pattern: str):
        if self.redis:
            try:
                cursor = 0
                while True:
                    cursor, keys = await self.redis.scan(cursor, match=pattern)
                    if keys:
                        await self.redis.delete(*keys)
                    if cursor == 0:
                        break
            except Exception:
                pass
        # 内存缓存降级：简单前缀匹配
        to_delete = [k for k in self._memory if pattern.replace("*", "") in k]
        for k in to_delete:
            self._memory.pop(k, None)


def cached(category: str):
    """缓存装饰器: 自动管理 get/set"""

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            cache: CacheManager = self.cache
            cache_args = args + tuple(sorted(kwargs.values()))
            # 尝试读缓存
            cached_data = await cache.get(category, *cache_args)
            if cached_data is not None:
                return cached_data
            # 执行原函数
            result = await func(self, *args, **kwargs)
            # 写缓存
            await cache.set(category, *cache_args, value=result)
            return result

        return wrapper

    return decorator


async def get_cache_manager() -> CacheManager:
    """获取缓存管理器（Redis不可用时使用内存缓存）"""
    global redis_client, _redis_unavailable
    if not redis_client and not _redis_unavailable:
        await init_redis()
    return CacheManager(redis_client)
