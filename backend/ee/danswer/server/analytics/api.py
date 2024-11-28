import datetime
from collections import defaultdict
from typing import Any

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from danswer.auth.users import current_admin_user
from danswer.db.engine import get_session
from danswer.db.models import User
from ee.danswer.db.analytics import fetch_danswerbot_analytics
from ee.danswer.db.analytics import fetch_per_user_query_analytics
from ee.danswer.db.analytics import fetch_persona_message_analytics
from ee.danswer.db.analytics import fetch_persona_unique_users
from ee.danswer.db.analytics import fetch_query_analytics

router = APIRouter(prefix="/analytics")


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
            datetime.datetime.utcnow() - datetime.timedelta(days=30)
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
            datetime.datetime.utcnow() - datetime.timedelta(days=30)
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


class DanswerbotAnalyticsResponse(BaseModel):
    total_queries: int
    auto_resolved: int
    date: datetime.date


@router.get("/admin/danswerbot")
def get_danswerbot_analytics(
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[DanswerbotAnalyticsResponse]:
    daily_danswerbot_info = fetch_danswerbot_analytics(
        start=start
        or (
            datetime.datetime.utcnow() - datetime.timedelta(days=30)
        ),  # default is 30d lookback
        end=end or datetime.datetime.utcnow(),
        db_session=db_session,
    )

    resolution_results = [
        DanswerbotAnalyticsResponse(
            total_queries=total_queries,
            # If it hits negatives, something has gone wrong...
            auto_resolved=max(0, total_queries - total_negatives),
            date=date,
        )
        for total_queries, total_negatives, date in daily_danswerbot_info
    ]

    return resolution_results


class PersonaMessageAnalyticsResponse(BaseModel):
    total_messages: int
    date: datetime.date
    persona_id: int


@router.get("/admin/persona/messages")
def get_persona_messages(
    persona_ids: str = Query(...),  # ... means this parameter is required
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[PersonaMessageAnalyticsResponse]:
    """Fetch daily message counts for multiple personas within the given time range."""
    # Convert comma-separated string to list of integers
    parsed_persona_ids = [
        int(id.strip()) for id in persona_ids.split(",") if id.strip()
    ]
    persona_message_counts = []
    start = start or (datetime.datetime.utcnow() - datetime.timedelta(days=30))
    end = end or datetime.datetime.utcnow()
    for persona_id in parsed_persona_ids:
        for count, date in fetch_persona_message_analytics(
            db_session=db_session,
            persona_id=int(persona_id),
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


@router.get("/admin/persona/unique-users")
def get_persona_unique_users(
    persona_ids: str,
    start: datetime.datetime,
    end: datetime.datetime,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    """Get unique users per day for each persona."""
    persona_id_list = [int(pid) for pid in persona_ids.split(",")]
    results = []
    for persona_id in persona_id_list:
        daily_counts = fetch_persona_unique_users(
            db_session=db_session,
            persona_id=persona_id,
            start=start,
            end=end,
        )
        for count, date in daily_counts:
            results.append(
                {
                    "unique_users": count,
                    "date": date.isoformat(),
                    "persona_id": persona_id,
                }
            )
    return results
