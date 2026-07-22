from collections import defaultdict
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.api_key import is_api_key_email_address
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import (
    TokenRateLimit,
    TokenRateLimit__UserGroup,
    User,
    User__UserGroup,
    UserGroup,
)
from onyx.db.token_limit import fetch_all_user_token_rate_limits
from onyx.db.user_usage import (
    TokenUsageBucket,
    get_group_token_buckets_since,
    get_user_token_buckets_since,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.query_and_chat.token_limit import (
    _get_cutoff_time,
    _is_rate_limited,
    _user_is_rate_limited_by_global,
)
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel


def _check_token_rate_limits(user: User) -> None:
    # Anonymous users are only rate limited by global settings
    if user.is_anonymous:
        _user_is_rate_limited_by_global()

    elif is_api_key_email_address(user.email):
        # API keys are only rate limited by global settings
        _user_is_rate_limited_by_global()

    else:
        run_functions_tuples_in_parallel(
            [
                (_user_is_rate_limited, (user.id,)),
                (_user_is_rate_limited_by_group, (user.id,)),
                (_user_is_rate_limited_by_global, ()),
            ]
        )


"""
User rate limits
"""


def _user_is_rate_limited(user_id: UUID) -> None:
    with get_session_with_current_tenant() as db_session:
        user_rate_limits = fetch_all_user_token_rate_limits(
            db_session=db_session, enabled_only=True, ordered=False
        )

        if user_rate_limits:
            user_cutoff_time = _get_cutoff_time(user_rate_limits)
            user_usage = _fetch_user_usage(user_id, user_cutoff_time, db_session)

            if _is_rate_limited(user_rate_limits, user_usage):
                raise OnyxError(
                    OnyxErrorCode.RATE_LIMITED,
                    "Token budget exceeded for user. Try again later.",
                )


def _fetch_user_usage(
    user_id: UUID, cutoff_time: datetime, db_session: Session
) -> list[TokenUsageBucket]:
    return get_user_token_buckets_since(db_session, str(user_id), cutoff_time)


"""
User Group rate limits
"""


def _user_is_rate_limited_by_group(user_id: UUID) -> None:
    with get_session_with_current_tenant() as db_session:
        group_rate_limits = _fetch_all_user_group_rate_limits(user_id, db_session)

        if group_rate_limits:
            # Group cutoff time is the same for all groups.
            # This could be optimized to only fetch the maximum cutoff time for
            # a specific group, but seems unnecessary for now.
            group_cutoff_time = _get_cutoff_time(
                [e for sublist in group_rate_limits.values() for e in sublist]
            )

            user_group_ids = list(group_rate_limits.keys())
            group_usage = _fetch_user_group_usage(
                user_group_ids, group_cutoff_time, db_session
            )

            has_at_least_one_untriggered_limit = False
            for user_group_id, rate_limits in group_rate_limits.items():
                usage = group_usage.get(user_group_id, [])

                if not _is_rate_limited(rate_limits, usage):
                    has_at_least_one_untriggered_limit = True
                    break

            if not has_at_least_one_untriggered_limit:
                raise OnyxError(
                    OnyxErrorCode.RATE_LIMITED,
                    "Token budget exceeded for user's groups. Try again later.",
                )


def _fetch_all_user_group_rate_limits(
    user_id: UUID, db_session: Session
) -> dict[int, list[TokenRateLimit]]:
    group_limits = (
        select(TokenRateLimit, User__UserGroup.user_group_id)
        .join(
            TokenRateLimit__UserGroup,
            TokenRateLimit.id == TokenRateLimit__UserGroup.rate_limit_id,
        )
        .join(
            UserGroup,
            UserGroup.id == TokenRateLimit__UserGroup.user_group_id,
        )
        .join(
            User__UserGroup,
            User__UserGroup.user_group_id == UserGroup.id,
        )
        .where(
            User__UserGroup.user_id == user_id,
            TokenRateLimit.enabled.is_(True),
        )
    )

    raw_rate_limits = db_session.execute(group_limits).all()

    group_rate_limits = defaultdict(list)
    for rate_limit, user_group_id in raw_rate_limits:
        group_rate_limits[user_group_id].append(rate_limit)

    return group_rate_limits


def _fetch_user_group_usage(
    user_group_ids: list[int], cutoff_time: datetime, db_session: Session
) -> dict[int, list[TokenUsageBucket]]:
    return get_group_token_buckets_since(db_session, user_group_ids, cutoff_time)
