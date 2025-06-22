from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.db.token_limit import delete_token_rate_limit
from onyx.db.token_limit import fetch_all_global_token_rate_limits
from onyx.db.token_limit import insert_global_token_rate_limit
from onyx.db.token_limit import update_token_rate_limit
from onyx.server.query_and_chat.token_limit import any_rate_limit_exists
from onyx.server.token_rate_limits.models import TokenRateLimitArgs
from onyx.server.token_rate_limits.models import TokenRateLimitDisplay

router = APIRouter(prefix="/admin/token-rate-limits")


"""
Global Token Limit Settings
"""


@router.get("/global")
def get_global_token_limit_settings(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[TokenRateLimitDisplay]:
    return [
        TokenRateLimitDisplay.from_db(token_rate_limit)
        for token_rate_limit in fetch_all_global_token_rate_limits(db_session)
    ]


@router.post("/global")
def create_global_token_limit_settings(
    token_limit_settings: TokenRateLimitArgs,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> TokenRateLimitDisplay:
    rate_limit_display = TokenRateLimitDisplay.from_db(
        insert_global_token_rate_limit(db_session, token_limit_settings)
    )
    # clear cache in case this was the first rate limit created
    any_rate_limit_exists.cache_clear()
    return rate_limit_display


"""
General Token Limit Settings
"""


@router.put("/rate-limit/{token_rate_limit_id}")
def update_token_limit_settings(
    token_rate_limit_id: int,
    token_limit_settings: TokenRateLimitArgs,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> TokenRateLimitDisplay:
    return TokenRateLimitDisplay.from_db(
        update_token_rate_limit(
            db_session=db_session,
            token_rate_limit_id=token_rate_limit_id,
            token_rate_limit_settings=token_limit_settings,
        )
    )


@router.delete("/rate-limit/{token_rate_limit_id}")
def delete_token_limit_settings(
    token_rate_limit_id: int,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    return delete_token_rate_limit(
        db_session=db_session,
        token_rate_limit_id=token_rate_limit_id,
    )
