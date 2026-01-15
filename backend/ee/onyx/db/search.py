import uuid
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.engine.time_utils import get_db_current_time
from onyx.db.models import SearchQuery


def create_search_query(
    db_session: Session,
    user_id: UUID,
    query: str,
    query_expansions: list[str] | None = None,
) -> SearchQuery:
    """Create and persist a `SearchQuery` row.

    Notes:
    - `SearchQuery.id` is a UUID PK without a server-side default, so we generate it.
    - `created_at` is filled by the DB (server_default=now()).
    """
    search_query = SearchQuery(
        id=uuid.uuid4(),
        user_id=user_id,
        query=query,
        query_expansions=query_expansions,
    )
    db_session.add(search_query)
    db_session.commit()
    db_session.refresh(search_query)
    return search_query


def fetch_search_queries_for_user(
    db_session: Session,
    user_id: UUID,
    filter_days: int | None = None,
    limit: int | None = None,
) -> list[SearchQuery]:
    """Fetch `SearchQuery` rows for a user.

    Args:
        user_id: User UUID.
        filter_days: Optional time filter. If provided, only rows created within
            the last `filter_days` days are returned.
        limit: Optional max number of rows to return.
    """
    if filter_days is not None and filter_days <= 0:
        raise ValueError("filter_days must be > 0")

    stmt = select(SearchQuery).where(SearchQuery.user_id == user_id)

    if filter_days is not None and filter_days > 0:
        cutoff = get_db_current_time(db_session) - timedelta(days=filter_days)
        stmt = stmt.where(SearchQuery.created_at >= cutoff)

    stmt = stmt.order_by(SearchQuery.created_at.desc())

    if limit is not None:
        stmt = stmt.limit(limit)

    return list(db_session.scalars(stmt).all())
