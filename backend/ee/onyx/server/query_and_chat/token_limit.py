from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from itertools import groupby
from typing import Dict
from typing import List
from typing import Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.api_key import is_api_key_email_address
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ChatMessage
from onyx.db.models import ChatSession
from onyx.db.models import TokenRateLimit
from onyx.db.models import TokenRateLimit__UserGroup
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup
from onyx.db.token_limit import fetch_all_user_token_rate_limits
from onyx.server.query_and_chat.token_limit import _get_cutoff_time
from onyx.server.query_and_chat.token_limit import _is_rate_limited
from onyx.server.query_and_chat.token_limit import _user_is_rate_limited_by_global
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel


def _check_token_rate_limits(user: User | None) -> None:
    if user is None:
        # Unauthenticated users are only rate limited by global settings
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
                raise HTTPException(
                    status_code=429,
                    detail="Token budget exceeded for user. Try again later.",
                )


def _fetch_user_usage(
    user_id: UUID, cutoff_time: datetime, db_session: Session
) -> Sequence[tuple[datetime, int]]:
    """
    Fetch user usage within the cutoff time, grouped by minute
    """
    result = db_session.execute(
        select(
            func.date_trunc("minute", ChatMessage.time_sent),
            func.sum(ChatMessage.token_count),
        )
        .join(ChatSession, ChatMessage.chat_session_id == ChatSession.id)
        .where(ChatSession.user_id == user_id, ChatMessage.time_sent >= cutoff_time)
        .group_by(func.date_trunc("minute", ChatMessage.time_sent))
    ).all()

    return [(row[0], row[1]) for row in result]


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
                raise HTTPException(
                    status_code=429,
                    detail="Token budget exceeded for user's groups. Try again later.",
                )


def _fetch_all_user_group_rate_limits(
    user_id: UUID, db_session: Session
) -> Dict[int, List[TokenRateLimit]]:
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
) -> dict[int, list[Tuple[datetime, int]]]:
    """
    Fetch user group usage within the cutoff time, grouped by minute
    """
    user_group_usage = db_session.execute(
        select(
            func.sum(ChatMessage.token_count),
            func.date_trunc("minute", ChatMessage.time_sent),
            UserGroup.id,
        )
        .join(ChatSession, ChatMessage.chat_session_id == ChatSession.id)
        .join(User__UserGroup, User__UserGroup.user_id == ChatSession.user_id)
        .join(UserGroup, UserGroup.id == User__UserGroup.user_group_id)
        .filter(UserGroup.id.in_(user_group_ids), ChatMessage.time_sent >= cutoff_time)
        .group_by(func.date_trunc("minute", ChatMessage.time_sent), UserGroup.id)
    ).all()

    return {
        user_group_id: [(usage, time_sent) for time_sent, usage, _ in group_usage]
        for user_group_id, group_usage in groupby(
            user_group_usage, key=lambda row: row[2]
        )
    }
