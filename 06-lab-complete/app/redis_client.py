"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

redis.from_url() chỉ tạo client, KHÔNG kết nối ngay, nên app vẫn khởi động được
khi Redis chưa sẵn sàng. Timeout ngắn để request không treo khi Redis chết.
"""
import redis

from app.config import settings

r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=1,
)


def redis_healthy() -> bool:
    """Dùng cho GET /ready: không ping được Redis thì trả False."""
    try:
        return bool(r.ping())
    except Exception:
        return False
