import datetime
from collections import defaultdict

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

import danswer.db.models as db_models
from danswer.auth.users import current_admin_user
from danswer.db.engine import get_session
from ee.danswer.db.analytics import fetch_danswerbot_analytics
from ee.danswer.db.analytics import fetch_per_user_query_analytics
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
    _: db_models.User | None = Depends(current_admin_user),
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
    _: db_models.User | None = Depends(current_admin_user),
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
    _: db_models.User | None = Depends(current_admin_user),
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
