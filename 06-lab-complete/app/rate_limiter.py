"""
Rate limiting (tiêu chí 7) — sliding window bằng Redis sorted set.

Mỗi API key có một ZSET: member = id duy nhất của request, score = timestamp.
State nằm trong Redis nên dùng chung giữa các worker/instance và còn nguyên
sau khi restart agent.
"""
import hashlib
import time
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    limit = settings.rate_limit_per_minute
    # Không lưu API key thô trong Redis
    rkey = "rate:" + hashlib.sha256(key.encode()).hexdigest()[:32]
    now = time.time()

    try:
        pipe = r.pipeline()
        pipe.zremrangebyscore(rkey, 0, now - WINDOW_SECONDS)  # bỏ request ngoài cửa sổ
        pipe.zcard(rkey)
        _, count = pipe.execute()

        if count >= limit:
            oldest = r.zrange(rkey, 0, 0, withscores=True)
            retry_after = 1
            if oldest:
                retry_after = max(1, int(oldest[0][1] + WINDOW_SECONDS - now) + 1)
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Rate limit exceeded",
                    "limit": limit,
                    "window_seconds": WINDOW_SECONDS,
                    "retry_after_seconds": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        pipe = r.pipeline()
        pipe.zadd(rkey, {f"{now}:{uuid.uuid4().hex}": now})
        pipe.expire(rkey, WINDOW_SECONDS + 5)
        pipe.execute()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Rate limiter unavailable (Redis)")
