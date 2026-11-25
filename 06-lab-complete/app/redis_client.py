"""
Kết nối Redis dùng chung cho rate limiter, cost guard và readiness probe.
"""
import redis

from app.config import settings


def _normalize_redis_url(url: str) -> str:
    """Chuyển đổi scheme valkey:// (Render Key Value) sang redis:// tương thích redis-py."""
    if url.startswith("valkeys://"):
        return "rediss://" + url[len("valkeys://"):]
    if url.startswith("valkey://"):
        return "redis://" + url[len("valkey://"):]
    return url


# Lazy connection pool: không ping Redis lúc import để app vẫn khởi động được khi chưa có Redis
r = redis.from_url(
    _normalize_redis_url(settings.redis_url or "redis://localhost:6379/0"),
    decode_responses=True,
    socket_connect_timeout=1.5,
    socket_timeout=1.5,
)


def get_redis() -> redis.Redis:
    """Trả về Redis client dùng chung."""
    return r


def redis_healthy() -> bool:
    """Kiểm tra kết nối thực tới Redis cho endpoint GET /ready."""
    if not settings.redis_url:
        return False
    try:
        return bool(r.ping())
    except (redis.RedisError, OSError):
        return False
