"""
Production AI Agent — Part 6 Final Project.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import sys
import time

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import redis

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import get_redis, redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Định dạng mỗi dòng log của ứng dụng thành đúng 1 JSON object hợp lệ."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra_fields = getattr(record, "extra_fields", None)
        if isinstance(extra_fields, dict):
            payload.update(extra_fields)
        if record.exc_info:
            payload["error_type"] = record.exc_info[0].__name__ if record.exc_info[0] else "Exception"
        return json.dumps(payload, ensure_ascii=False)


def _configure_logger() -> logging.Logger:
    app_logger = logging.getLogger("agent")
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    app_logger.setLevel(level)
    app_logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    app_logger.addHandler(handler)
    app_logger.propagate = False
    return app_logger


logger = _configure_logger()
START_TIME = time.time()
_shutting_down = False


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"extra_fields": {"event": event, **fields}})


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Quản lý khởi tạo và graceful shutdown khi nhận SIGTERM từ orchestrator."""
    global _shutting_down
    _shutting_down = False
    log_event(
        "startup",
        environment=settings.environment,
        port=settings.port,
        rate_limit_per_minute=settings.rate_limit_per_minute,
        daily_budget_usd=settings.daily_budget_usd,
    )
    yield
    _shutting_down = True
    log_event("shutdown", reason="SIGTERM_or_lifespan_exit")
    try:
        get_redis().close()
    except Exception:
        pass


app = FastAPI(
    title="Production AI Agent",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if settings.environment == "production" else "/docs",
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    log_event("validation_error", level=logging.WARNING, path=request.url.path)
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Invalid request payload",
            "errors": [
                {"loc": list(err.get("loc", ())), "msg": err.get("msg", "Invalid value")}
                for err in exc.errors()
            ],
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log_event(
        "unhandled_error",
        level=logging.ERROR,
        path=request.url.path,
        error_class=type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default="anonymous", max_length=128)


def _append_history(user_id: str, question: str, answer: str) -> None:
    """Lưu lịch sử hội thoại ngắn gọn vào Redis (stateless)."""
    try:
        client = get_redis()
        key = f"history:{user_id}"
        entry = json.dumps(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "question": question,
                "answer": answer,
            },
            ensure_ascii=False,
        )
        pipe = client.pipeline()
        pipe.rpush(key, entry)
        pipe.ltrim(key, -20, -1)
        pipe.expire(key, 3600)
        pipe.execute()
    except (redis.RedisError, OSError):
        pass


@app.get("/health")
def health():
    """Liveness probe: luôn trả 200 khi process còn sống, không phụ thuộc Redis."""
    return {
        "status": "ok",
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - START_TIME, 2),
    }


@app.get("/ready")
def ready():
    """Readiness probe: trả 200 khi Redis kết nối tốt, 503 khi mất kết nối hoặc đang tắt."""
    if _shutting_down or not redis_healthy():
        log_event("readiness_failed", level=logging.WARNING, shutting_down=_shutting_down)
        raise HTTPException(status_code=503, detail="Service not ready: Redis unavailable")
    return {"status": "ready", "redis": "connected"}


@app.post("/ask")
async def ask(
    body: AskRequest,
    request: Request,
    api_key: str = Depends(verify_api_key),
):
    started = time.perf_counter()
    check_rate_limit(api_key)
    check_budget()

    answer = await asyncio.to_thread(llm_ask, body.question)

    input_tokens = max(1, len(body.question) // 4)
    output_tokens = max(1, len(answer) // 4)
    cost_usd = record_cost(input_tokens, output_tokens)

    user_id = body.user_id or "anonymous"
    _append_history(user_id, body.question, answer)

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    log_event(
        "ask_completed",
        path=request.url.path,
        status=200,
        user_id=user_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(cost_usd, 8),
        duration_ms=duration_ms,
    )
    return {
        "question": body.question,
        "answer": answer,
        "user_id": user_id,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost_usd, 8),
        },
    }
