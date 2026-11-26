"""
Production AI Agent — Part 6 Final Project

Luồng /ask: auth → rate limit → budget → LLM → record_cost.
Chạy: uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask


# ── Structured logging: mỗi dòng log của app là 1 JSON object ──
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if extra:
            entry.update(extra)
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def setup_logging() -> logging.Logger:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    return logging.getLogger("agent")


logger = setup_logging()


def log(event: str, **fields) -> None:
    logger.info(event, extra={"fields": fields})


# ── Lifespan: log khi start/stop. Không tự đăng ký handler SIGTERM,
#    để uvicorn tự xử lý (ngừng nhận request mới, chờ request đang chạy, exit 0) ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    log("startup", environment=settings.environment, port=settings.port)
    yield
    log("shutdown")


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = None


@app.middleware("http")
async def access_log(request: Request, call_next):
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        log(
            "request",
            path=request.url.path,
            method=request.method,
            status=status,
            ms=round((time.perf_counter() - start) * 1000, 1),
        )


# ── Lỗi trả về rõ ràng, không lộ stack trace ──
@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    errors = [
        {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"error": "Invalid request", "details": errors})


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    logger.error("unhandled_error", exc_info=exc)  # stack trace chỉ vào log, không ra client
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


@app.get("/health")
def health():
    """Liveness: luôn 200 khi process còn chạy, kể cả khi Redis chết."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness: 503 khi Redis không kết nối được."""
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis not available")
    return {"ready": True}


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)  # ước lượng ~4 ký tự / token


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()
    answer = llm_ask(body.question)
    cost = record_cost(_tokens(body.question), _tokens(answer))
    log("ask", q_len=len(body.question), cost_usd=round(cost, 8))
    return {"question": body.question, "answer": answer}
