"""
API Key authentication (tiêu chí 6).

Header X-API-Key phải trùng AGENT_API_KEY. Thiếu hoặc sai → 401 (không phải 403/422).
auto_error=False để tự trả 401, thay vì để FastAPI trả 403 khi thiếu header.
"""
import hmac

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from app.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """Dependency cho FastAPI — dùng trong /ask: Depends(verify_api_key)."""
    expected = settings.agent_api_key
    if (
        not api_key
        or not expected
        or not hmac.compare_digest(api_key.encode(), expected.encode())
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Send header: X-API-Key: <key>",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return api_key
