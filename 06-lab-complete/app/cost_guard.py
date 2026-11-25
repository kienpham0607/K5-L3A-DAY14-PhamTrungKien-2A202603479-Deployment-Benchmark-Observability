"""
Cost guard (tiêu chí 8) — Theo dõi và khóa trần chi phí LLM bằng Redis.
"""
from datetime import datetime, timezone

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import get_redis

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006


def _daily_key() -> str:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"cost:daily:{day}"


def _monthly_key() -> str:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return f"cost:monthly:{month}"


def _active_budget_usd() -> float:
    return min(settings.daily_budget_usd, settings.monthly_budget_usd)


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    client = get_redis()
    try:
        daily_spent = float(client.get(_daily_key()) or 0.0)
        monthly_spent = float(client.get(_monthly_key()) or 0.0)
    except (redis.RedisError, OSError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Cost guard store (Redis) is currently unavailable.",
        ) from exc

    if daily_spent >= settings.daily_budget_usd or monthly_spent >= settings.monthly_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "LLM budget exceeded",
                "daily_spent_usd": round(daily_spent, 8),
                "daily_budget_usd": settings.daily_budget_usd,
            },
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào Redis và trả về chi phí USD."""
    cost = (input_tokens / 1000.0) * PRICE_INPUT_PER_1K + (output_tokens / 1000.0) * PRICE_OUTPUT_PER_1K
    client = get_redis()
    daily_key = _daily_key()
    monthly_key = _monthly_key()
    try:
        pipe = client.pipeline()
        pipe.incrbyfloat(daily_key, cost)
        pipe.expire(daily_key, 2 * 24 * 3600)
        pipe.incrbyfloat(monthly_key, cost)
        pipe.expire(monthly_key, 35 * 24 * 3600)
        pipe.execute()
    except (redis.RedisError, OSError):
        pass
    return cost
