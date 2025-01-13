import datetime
from collections import defaultdict

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ee.onyx.db.analytics import fetch_onyxbot_analytics
from ee.onyx.db.analytics import fetch_per_user_query_analytics
from ee.onyx.db.analytics import fetch_persona_message_analytics
from ee.onyx.db.analytics import fetch_persona_unique_users
from ee.onyx.db.analytics import fetch_query_analytics
from onyx.auth.users import current_admin_user
from onyx.db.engine import get_session
from onyx.db.models import User

router = APIRouter(prefix="/analytics")


_DEFAULT_LOOKBACK_DAYS = 30


class QueryAnalyticsResponse(BaseModel):
    total_queries: int
    total_likes: int
    total_dislikes: int
    date: datetime.date


@router.get("/admin/query")
def get_query_analytics(
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[QueryAnalyticsResponse]:
    daily_query_usage_info = fetch_query_analytics(
        start=start
        or (
            datetime.datetime.utcnow() - datetime.timedelta(days=_DEFAULT_LOOKBACK_DAYS)
        ),  # default is 30d lookback
        end=end or datetime.datetime.utcnow(),
        db_session=db_session,
    )
    return [
        QueryAnalyticsResponse(
            total_queries=total_queries,
            total_likes=total_likes,
            total_dislikes=total_dislikes,
            date=date,
        )
        for total_queries, total_likes, total_dislikes, date in daily_query_usage_info
    ]


class UserAnalyticsResponse(BaseModel):
    total_active_users: int
    date: datetime.date


@router.get("/admin/user")
def get_user_analytics(
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[UserAnalyticsResponse]:
    daily_query_usage_info_per_user = fetch_per_user_query_analytics(
        start=start
        or (
            datetime.datetime.utcnow() - datetime.timedelta(days=_DEFAULT_LOOKBACK_DAYS)
        ),  # default is 30d lookback
        end=end or datetime.datetime.utcnow(),
        db_session=db_session,
    )

    user_analytics: dict[datetime.date, int] = defaultdict(int)
    for __, ___, ____, date, _____ in daily_query_usage_info_per_user:
        user_analytics[date] += 1
    return [
        UserAnalyticsResponse(
            total_active_users=cnt,
            date=date,
        )
        for date, cnt in user_analytics.items()
    ]


class OnyxbotAnalyticsResponse(BaseModel):
    total_queries: int
    auto_resolved: int
    date: datetime.date


@router.get("/admin/onyxbot")
def get_onyxbot_analytics(
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[OnyxbotAnalyticsResponse]:
    daily_onyxbot_info = fetch_onyxbot_analytics(
        start=start
        or (
            datetime.datetime.utcnow() - datetime.timedelta(days=_DEFAULT_LOOKBACK_DAYS)
        ),  # default is 30d lookback
        end=end or datetime.datetime.utcnow(),
        db_session=db_session,
    )

    resolution_results = [
        OnyxbotAnalyticsResponse(
            total_queries=total_queries,
            # If it hits negatives, something has gone wrong...
            auto_resolved=max(0, total_queries - total_negatives),
            date=date,
        )
        for total_queries, total_negatives, date in daily_onyxbot_info
    ]

    return resolution_results


class PersonaMessageAnalyticsResponse(BaseModel):
    total_messages: int
    date: datetime.date
    persona_id: int


@router.get("/admin/persona/messages")
def get_persona_messages(
    persona_id: int,
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[PersonaMessageAnalyticsResponse]:
    """Fetch daily message counts for a single persona within the given time range."""
    start = start or (
        datetime.datetime.utcnow() - datetime.timedelta(days=_DEFAULT_LOOKBACK_DAYS)
    )
    end = end or datetime.datetime.utcnow()

    persona_message_counts = []
    for count, date in fetch_persona_message_analytics(
        db_session=db_session,
        persona_id=persona_id,
        start=start,
        end=end,
    ):
        persona_message_counts.append(
            PersonaMessageAnalyticsResponse(
                total_messages=count,
                date=date,
                persona_id=persona_id,
            )
        )

    return persona_message_counts


class PersonaUniqueUsersResponse(BaseModel):
    unique_users: int
    date: datetime.date
    persona_id: int


@router.get("/admin/persona/unique-users")
def get_persona_unique_users(
    persona_id: int,
    start: datetime.datetime,
    end: datetime.datetime,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[PersonaUniqueUsersResponse]:
    """Get unique users per day for a single persona."""
    unique_user_counts = []
    daily_counts = fetch_persona_unique_users(
        db_session=db_session,
        persona_id=persona_id,
        start=start,
        end=end,
    )
    for count, date in daily_counts:
        unique_user_counts.append(
            PersonaUniqueUsersResponse(
                unique_users=count,
                date=date,
                persona_id=persona_id,
            )
        )
    return unique_user_counts
