from collections import defaultdict

from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from ee.onyx.db.token_limit import fetch_all_user_group_token_rate_limits_by_group
from ee.onyx.db.token_limit import fetch_user_group_token_rate_limits_for_group
from ee.onyx.db.token_limit import insert_user_group_token_rate_limit
from onyx.auth.permissions import require_permission
from onyx.auth.scoped_permissions import assert_manages_group
from onyx.auth.scoped_permissions import assert_within_scope
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.configs.constants import TokenRateLimitScope
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.db.token_limit import delete_token_rate_limit
from onyx.db.token_limit import fetch_all_user_token_rate_limits
from onyx.db.token_limit import get_token_rate_limit_scope_and_group
from onyx.db.token_limit import insert_user_token_rate_limit
from onyx.db.token_limit import update_token_rate_limit
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.query_and_chat.token_limit import any_rate_limit_exists
from onyx.server.token_rate_limits.models import TokenRateLimitArgs
from onyx.server.token_rate_limits.models import TokenRateLimitDisplay

router = APIRouter(prefix="/admin/token-rate-limits", tags=PUBLIC_API_TAGS)


"""
Group Token Limit Settings
"""


@router.get("/user-groups")
def get_all_group_token_limit_settings(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> dict[str, list[TokenRateLimitDisplay]]:
    user_groups_to_token_rate_limits = fetch_all_user_group_token_rate_limits_by_group(
        db_session
    )

    token_rate_limits_by_group = defaultdict(list)
    for token_rate_limit, group_name in user_groups_to_token_rate_limits:
        token_rate_limits_by_group[group_name].append(
            TokenRateLimitDisplay.from_db(token_rate_limit)
        )

    return dict(token_rate_limits_by_group)


@router.get("/user-group/{group_id}")
def get_group_token_limit_settings(
    group_id: int,
    user: User = Depends(
        require_permission(Permission.MANAGE_USER_GROUPS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> list[TokenRateLimitDisplay]:
    # GATE 2 (read): a scoped manager may only read limits for a group they manage
    # (global holders bypass). Single-group path param, so assert_manages_group, not a clause.
    assert_manages_group(user, db_session, group_id=group_id)
    return [
        TokenRateLimitDisplay.from_db(token_rate_limit)
        for token_rate_limit in fetch_user_group_token_rate_limits_for_group(
            db_session=db_session,
            group_id=group_id,
        )
    ]


@router.post("/user-group/{group_id}")
def create_group_token_limit_settings(
    group_id: int,
    token_limit_settings: TokenRateLimitArgs,
    user: User = Depends(
        require_permission(Permission.MANAGE_USER_GROUPS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> TokenRateLimitDisplay:
    # GATE 2: a scoped manager may only set a token limit on a group they manage
    # (admins bypass). Token limits have no privacy dimension, so is_non_public=True.
    assert_within_scope(
        user,
        db_session,
        permission=Permission.MANAGE_USER_GROUPS,
        current_group_ids=[group_id],
        requested_group_ids=[group_id],
        is_non_public=True,
    )
    rate_limit_display = TokenRateLimitDisplay.from_db(
        insert_user_group_token_rate_limit(
            db_session=db_session,
            token_rate_limit_settings=token_limit_settings,
            group_id=group_id,
        )
    )
    # clear cache in case this was the first rate limit created
    any_rate_limit_exists.cache_clear()
    return rate_limit_display


def _authorize_group_token_rate_limit_write(
    user: User, db_session: Session, *, group_id: int, rate_limit_id: int
) -> None:
    """Manager-scope gate for a group token-limit write: caller must manage group_id AND
    the limit must belong to it — so a global/per-user id or another group's limit can't be
    reached through this path."""
    assert_within_scope(
        user,
        db_session,
        permission=Permission.MANAGE_USER_GROUPS,
        current_group_ids=[group_id],
        requested_group_ids=[group_id],
        is_non_public=True,
    )
    scope, resolved_group_id = get_token_rate_limit_scope_and_group(
        db_session, rate_limit_id
    )
    if scope != TokenRateLimitScope.USER_GROUP or resolved_group_id != group_id:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND, "Token rate limit not found for this group."
        )


# Separate from the shared by-id routes so this route's require_permission caps a scoped
# PAT to MANAGE_USER_GROUPS; a shared route would expose FULL_ADMIN global/user limits.
@router.put("/user-group/{group_id}/rate-limit/{rate_limit_id}")
def update_group_token_limit_settings(
    group_id: int,
    rate_limit_id: int,
    token_limit_settings: TokenRateLimitArgs,
    user: User = Depends(
        require_permission(Permission.MANAGE_USER_GROUPS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> TokenRateLimitDisplay:
    _authorize_group_token_rate_limit_write(
        user, db_session, group_id=group_id, rate_limit_id=rate_limit_id
    )
    rate_limit_display = TokenRateLimitDisplay.from_db(
        update_token_rate_limit(
            db_session=db_session,
            token_rate_limit_id=rate_limit_id,
            token_rate_limit_settings=token_limit_settings,
        )
    )
    any_rate_limit_exists.cache_clear()
    return rate_limit_display


@router.delete("/user-group/{group_id}/rate-limit/{rate_limit_id}")
def delete_group_token_limit_settings(
    group_id: int,
    rate_limit_id: int,
    user: User = Depends(
        require_permission(Permission.MANAGE_USER_GROUPS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> None:
    _authorize_group_token_rate_limit_write(
        user, db_session, group_id=group_id, rate_limit_id=rate_limit_id
    )
    delete_token_rate_limit(db_session=db_session, token_rate_limit_id=rate_limit_id)
    any_rate_limit_exists.cache_clear()


"""
User Token Limit Settings
"""


@router.get("/users")
def get_user_token_limit_settings(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[TokenRateLimitDisplay]:
    return [
        TokenRateLimitDisplay.from_db(token_rate_limit)
        for token_rate_limit in fetch_all_user_token_rate_limits(db_session)
    ]


@router.post("/users")
def create_user_token_limit_settings(
    token_limit_settings: TokenRateLimitArgs,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> TokenRateLimitDisplay:
    rate_limit_display = TokenRateLimitDisplay.from_db(
        insert_user_token_rate_limit(db_session, token_limit_settings)
    )
    # clear cache in case this was the first rate limit created
    any_rate_limit_exists.cache_clear()
    return rate_limit_display
