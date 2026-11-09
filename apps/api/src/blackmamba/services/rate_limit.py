"""Fixed-window rate limiter for login (NFR-1). Redis in production, memory for tests/dev."""

import time
from collections import defaultdict
from functools import lru_cache
from typing import Protocol

from redis.asyncio import Redis

from blackmamba.core.config import get_settings


class RateLimiter(Protocol):
    async def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        """Count one attempt. Returns False when the limit is exceeded."""

    async def reset(self, key: str) -> None: ...


class MemoryRateLimiter:
    def __init__(self) -> None:
        self._windows: dict[str, tuple[float, int]] = defaultdict(lambda: (0.0, 0))

    async def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        start, count = self._windows[key]
        if now - start >= window_seconds:
            start, count = now, 0
        count += 1
        self._windows[key] = (start, count)
        return count <= limit

    async def reset(self, key: str) -> None:
        self._windows.pop(key, None)


class RedisRateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        full_key = f"bm:rl:{key}"
        count = int(await self._redis.incr(full_key))
        if count == 1:
            await self._redis.expire(full_key, window_seconds)
        return count <= limit

    async def reset(self, key: str) -> None:
        await self._redis.delete(f"bm:rl:{key}")


@lru_cache
def get_rate_limiter() -> RateLimiter:
    settings = get_settings()
    if settings.rate_limit_backend == "redis":
        return RedisRateLimiter(Redis.from_url(settings.redis_url))
    return MemoryRateLimiter()
