"""
Rate limiting (tiêu chí 7) — Sliding window 60 giây lưu trong Redis Sorted Set.
"""
import hashlib
import time
import uuid

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import get_redis

WINDOW_SECONDS = 60

_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = window
    if oldest and oldest[2] then
        retry_after = math.max(1, math.ceil(window - (now - tonumber(oldest[2]))))
    end
    return {0, retry_after}
end

redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, window + 5)
return {1, limit - count - 1}
"""


def check_rate_limit(key: str) -> None:
    """Giới hạn tối đa RATE_LIMIT_PER_MINUTE request / 60s cho mỗi API key trong Redis."""
    client = get_redis()
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    redis_key = f"ratelimit:{key_hash}"
    now = time.time()
    member = f"{now:.6f}:{uuid.uuid4().hex[:8]}"

    try:
        allowed, value = client.eval(
            _SLIDING_WINDOW_LUA,
            1,
            redis_key,
            now,
            WINDOW_SECONDS,
            settings.rate_limit_per_minute,
            member,
        )
    except (redis.RedisError, OSError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Rate limit store (Redis) is currently unavailable.",
        ) from exc

    if not int(allowed):
        retry_after = max(1, int(value))
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "limit_per_minute": settings.rate_limit_per_minute,
                "retry_after_seconds": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )
