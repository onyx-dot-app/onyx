"""API key and PAT usage tracking for cloud usage limits."""

from fastapi import Depends
from fastapi import Request
from sqlalchemy.orm import Session

from onyx.auth.api_key import get_hashed_api_key_from_request
from onyx.auth.pat import get_hashed_pat_from_request
from onyx.db.engine.sql_engine import get_session
from onyx.db.usage import increment_usage
from onyx.db.usage import UsageType
from onyx.server.usage_limits import check_usage_and_raise
from onyx.server.usage_limits import is_usage_limits_enabled
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


def check_api_key_usage(
    request: Request,
    db_session: Session = Depends(get_session),
) -> None:
    """
    FastAPI dependency that checks and tracks API key/PAT usage limits.

    This should be added as a dependency to endpoints that accept API key
    or PAT authentication and should be usage-limited.
    """
    if not is_usage_limits_enabled():
        return

    # Check if request is authenticated via API key or PAT
    is_api_key_request = get_hashed_api_key_from_request(request) is not None
    is_pat_request = get_hashed_pat_from_request(request) is not None

    if not is_api_key_request and not is_pat_request:
        return

    tenant_id = get_current_tenant_id()

    # Check usage limit
    check_usage_and_raise(
        db_session=db_session,
        usage_type=UsageType.API_CALLS,
        tenant_id=tenant_id,
        pending_amount=1,
    )

    # Increment usage counter
    increment_usage(
        db_session=db_session,
        usage_type=UsageType.API_CALLS,
        amount=1,
    )
    db_session.commit()
