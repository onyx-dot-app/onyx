from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from onyx.db.enums import SystemUsageAttribution, UsageActorKind
from onyx.db.llm_usage import LLMUsageRecord
from onyx.db.models import UserUsage
from onyx.utils.datetime import datetime_to_utc

_CONFLICT_COLUMNS = [
    "system_attribution",
    "window_start",
    "model",
    "flow",
    "provider",
]
_SYSTEM_ACTOR_INDEX_PREDICATE = text("actor_kind = 'SYSTEM'")


class SystemTokenUsageBucket(BaseModel):
    window_start: datetime
    tokens: int


def record_system_usage(
    db_session: Session,
    attribution: SystemUsageAttribution,
    usage: LLMUsageRecord,
) -> None:
    """Accumulate one non-user generation into its daily rollup."""
    statement = pg_insert(UserUsage).values(
        user_id=None,
        actor_kind=UsageActorKind.SYSTEM,
        system_attribution=attribution,
        window_start=usage.window_start,
        model=usage.model,
        flow=usage.flow,
        provider=usage.provider or "",
        incognito=False,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_creation_tokens=usage.cache_creation_tokens,
        cost_cents=usage.cost_cents,
    )
    statement = statement.on_conflict_do_update(
        index_elements=_CONFLICT_COLUMNS,
        index_where=_SYSTEM_ACTOR_INDEX_PREDICATE,
        set_={
            "input_tokens": UserUsage.input_tokens + statement.excluded.input_tokens,
            "output_tokens": (
                UserUsage.output_tokens + statement.excluded.output_tokens
            ),
            "cache_read_tokens": (
                UserUsage.cache_read_tokens + statement.excluded.cache_read_tokens
            ),
            "cache_creation_tokens": (
                UserUsage.cache_creation_tokens
                + statement.excluded.cache_creation_tokens
            ),
            "cost_cents": UserUsage.cost_cents + statement.excluded.cost_cents,
        },
    )
    db_session.execute(statement)
    db_session.flush()


def get_system_cost_cents_since(db_session: Session, cutoff: datetime) -> float:
    total = db_session.scalar(
        select(func.coalesce(func.sum(UserUsage.cost_cents), 0.0)).where(
            UserUsage.actor_kind == UsageActorKind.SYSTEM,
            UserUsage.window_start >= cutoff,
        )
    )
    return float(total or 0.0)


def get_system_cost_cents_buckets_since(
    db_session: Session, cutoff: datetime
) -> list[tuple[datetime, float]]:
    rows = db_session.execute(
        select(
            UserUsage.window_start,
            func.coalesce(func.sum(UserUsage.cost_cents), 0.0),
        )
        .where(
            UserUsage.actor_kind == UsageActorKind.SYSTEM,
            UserUsage.window_start >= cutoff,
        )
        .group_by(UserUsage.window_start)
    ).all()
    return [(datetime_to_utc(window_start), float(cost)) for window_start, cost in rows]


def get_system_token_buckets_since(
    db_session: Session, cutoff: datetime
) -> list[SystemTokenUsageBucket]:
    rows = db_session.execute(
        select(
            UserUsage.window_start,
            func.sum(UserUsage.input_tokens + UserUsage.output_tokens),
        )
        .where(
            UserUsage.actor_kind == UsageActorKind.SYSTEM,
            UserUsage.window_start >= cutoff,
        )
        .group_by(UserUsage.window_start)
        .order_by(UserUsage.window_start)
    ).all()
    return [
        SystemTokenUsageBucket(
            window_start=datetime_to_utc(window_start), tokens=int(tokens)
        )
        for window_start, tokens in rows
    ]
