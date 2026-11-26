"""
Cost guard (tiêu chí 8).

Chi phí LLM cộng dồn theo ngày (UTC) vào Redis bằng INCRBYFLOAT (atomic, dùng chung
giữa các worker). Tổng chi phí >= DAILY_BUDGET_USD → HTTP 402.
"""
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006


def _key() -> str:
    return "cost:" + datetime.now(timezone.utc).strftime("%Y-%m-%d")


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    try:
        spent = float(r.get(_key()) or 0.0)
    except Exception:
        raise HTTPException(status_code=503, detail="Cost guard unavailable (Redis)")
    if spent >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Daily budget exceeded",
                "used_usd": round(spent, 6),
                "budget_usd": settings.daily_budget_usd,
            },
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (input_tokens / 1000) * PRICE_INPUT_PER_1K + (output_tokens / 1000) * PRICE_OUTPUT_PER_1K
    try:
        key = _key()
        pipe = r.pipeline()
        pipe.incrbyfloat(key, cost)
        pipe.expire(key, 2 * 24 * 3600)
        pipe.execute()
    except Exception:
        # Không làm hỏng response đã có vì lỗi ghi chi phí
        pass
    return cost
