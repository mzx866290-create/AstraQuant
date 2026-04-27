"""多级缓存策略管理 (Redis可选，不可用时降级为内存缓存)"""
import json
from functools import wraps
from typing import Optional, Callable, Any
from datetime import timedelta
import logging
import os

logger = logging.getLogger(__name__)

# TTL策略
TTL_POLICY = {
    "realtime_quote": timedelta(seconds=5),
    "daily_kline": timedelta(hours=1),
    "weekly_kline": timedelta(hours=24),
    "stock_info": timedelta(hours=12),
    "financial_data": timedelta(days=1),
    "search_result": timedelta(minutes=30),
    "user_watchlist": timedelta(minutes=5),
}

redis_client: Optional[Any] = None
_redis_unavailable = False


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
        self._memory: dict = {}

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

    async def set(self, category: str, *args, value: Any):
        key = self._make_key(category, *args)
        ttl = TTL_POLICY.get(category, timedelta(minutes=10))
        if self.redis:
            try:
                await self.redis.setex(
                    key, int(ttl.total_seconds()), json.dumps(value, default=str)
                )
                return
            except Exception:
                pass
        # 内存缓存降级
        import time
        self._memory[key] = {
            "value": value,
            "expires": time.time() + ttl.total_seconds(),
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