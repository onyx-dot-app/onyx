from cachetools import TTLCache
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from danswer.db.engine import get_session
from danswer.db.models import ApiKey
from danswer.utils.logger import setup_logger


logger = setup_logger()

_API_KEY_HEADER = "X-API-Key"
# Cache API keys for 24 hours (86400 seconds)
cache = TTLCache(maxsize=1000, ttl=86400)  # 24 * 60 * 60 seconds


def validate_api_key(request: Request, db_session: Session = Depends(get_session)):
    if _API_KEY_HEADER not in request.headers:
        return None

    api_key_value = request.headers.get(_API_KEY_HEADER)
    if not api_key_value:
        raise HTTPException(status_code=401, detail="Missing API key")

    # Check if the API key is in cache
    # This is a performance optimization to avoid database lookups
    if api_key_value in cache:
        return None

    api_key = db_session.scalar(
        select(ApiKey).where(ApiKey.hashed_api_key == api_key_value)
    )
    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # If we reach here, the API key is valid
    # Cache it for future requests
    cache[api_key_value] = True
    return None
