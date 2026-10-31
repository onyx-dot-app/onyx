"""Daily per-user LLM usage rollup for cost/token attribution.

A window rollup: rows accumulate in place per (user, window,
model, flow, provider, incognito), not an append-only per-call ledger."""

from collections import defaultdict
from collections.abc import Iterator, Sequence
from datetime import datetime, timedelta
from typing import Any, cast

from pydantic import BaseModel
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine.cursor import CursorResult
from sqlalchemy.orm import Session

from onyx.configs.constants import TokenRateLimitPeriod
from onyx.db.enums import UsageActorKind
from onyx.db.llm_usage import LLMUsageRecord, build_usage_upsert_values
from onyx.db.models import (
    USAGE_MODEL_CONFIGURATION_KEY,
    TokenRateLimit,
    User,
    User__UserGroup,
    UserUsage,
)
from onyx.utils.datetime import datetime_to_utc, get_window_start

USER_USAGE_BUCKET_SECONDS = 24 * 60 * 60
# Not email-shaped on purpose: it can never collide with a real address.
DELETED_USER_EXPORT_EMAIL = "(deleted user)"
_CONFLICT_COLS = [
    "user_id",
    "window_start",
    "model",
    "flow",
    "provider",
    "incognito",
    USAGE_MODEL_CONFIGURATION_KEY,
]
_USER_ACTOR_INDEX_PREDICATE = text("actor_kind = 'USER'")


class TokenUsageBucket(BaseModel):
    window_start: datetime
    tokens: int


def get_period_window_start(now: datetime, period: TokenRateLimitPeriod) -> datetime:
    """Start of the current UTC calendar window for `period`."""
    today = get_window_start(now, USER_USAGE_BUCKET_SECONDS)
    if period == TokenRateLimitPeriod.DAILY:
        return today
    if period == TokenRateLimitPeriod.WEEKLY:
        return today - timedelta(days=today.weekday())
    return today.replace(day=1)


def get_period_window_reset(now: datetime, period: TokenRateLimitPeriod) -> datetime:
    window_start = get_period_window_start(now, period)
    if period == TokenRateLimitPeriod.DAILY:
        return window_start + timedelta(days=1)
    if period == TokenRateLimitPeriod.WEEKLY:
        return window_start + timedelta(days=7)
    if window_start.month == 12:
        return window_start.replace(year=window_start.year + 1, month=1)
    return window_start.replace(month=window_start.month + 1)


def period_fetch_cutoff(
    now: datetime, rate_limits: Sequence[TokenRateLimit]
) -> datetime:
    """Earliest window start across the limits, so one fetch covers every window."""
    return min(get_period_window_start(now, limit.period) for limit in rate_limits)


def token_budget_limits(rate_limits: Sequence[TokenRateLimit]) -> list[TokenRateLimit]:
    # A non-positive budget can only come from legacy rows; never block on it.
    return [
        limit
        for limit in rate_limits
        if limit.token_budget is not None and limit.token_budget > 0
    ]


def cost_budget_limits(rate_limits: Sequence[TokenRateLimit]) -> list[TokenRateLimit]:
    return [limit for limit in rate_limits if limit.cost_budget_cents is not None]


class UserUsageByDay(BaseModel):
    """Per-user usage aggregated by UTC calendar day and model."""

    day: str  # YYYY-MM-DD
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cost_cents: float


class UsageExportRow(BaseModel):
    email: str
    model: str
    flow: str
    provider: str
    incognito: bool
    day: str  # YYYY-MM-DD
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cost_cents: float


def record_user_usage(
    db_session: Session,
    user_id: str,
    usage: LLMUsageRecord,
    incognito: bool = False,
) -> None:
    """Atomically accumulate into the ledger (Postgres upsert). Caller commits."""
    # Store "" rather than NULL for a missing provider so the dedup unique index
    # collapses these rows on every Postgres version (no NULLS NOT DISTINCT).
    provider = usage.provider or ""
    stmt = pg_insert(UserUsage).values(
        user_id=user_id,
        actor_kind=UsageActorKind.USER,
        window_start=usage.window_start,
        model=usage.model,
        flow=usage.flow,
        provider=provider,
        incognito=incognito,
        model_configuration_id=usage.model_configuration_id,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_creation_tokens=usage.cache_creation_tokens,
        cost_cents=usage.cost_cents,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=_CONFLICT_COLS,
        index_where=_USER_ACTOR_INDEX_PREDICATE,
        set_=build_usage_upsert_values(stmt),
    )
    db_session.execute(stmt)
    db_session.flush()


def get_user_usage_by_day_and_model(
    db_session: Session,
    user_id: str,
    since: datetime,
    until: datetime,
) -> list[UserUsageByDay]:
    """Sum usage by UTC day and model over [since, until)."""
    utc_day = func.date(func.timezone("UTC", UserUsage.window_start))
    rows = db_session.execute(
        select(
            utc_day.label("day"),
            UserUsage.model,
            func.sum(UserUsage.input_tokens),
            func.sum(UserUsage.output_tokens),
            func.sum(UserUsage.cache_read_tokens),
            func.sum(UserUsage.cache_creation_tokens),
            func.sum(UserUsage.cost_cents),
        )
        .where(
            UserUsage.user_id == user_id,
            UserUsage.window_start >= since,
            UserUsage.window_start < until,
        )
        .group_by(utc_day, UserUsage.model)
        .order_by(utc_day, UserUsage.model)
    ).all()

    return [
        UserUsageByDay(
            day=str(day),
            model=model,
            input_tokens=int(in_tok or 0),
            output_tokens=int(out_tok or 0),
            cache_read_tokens=int(cache_read_tok or 0),
            cache_creation_tokens=int(cache_creation_tok or 0),
            cost_cents=float(cost or 0.0),
        )
        for (
            day,
            model,
            in_tok,
            out_tok,
            cache_read_tok,
            cache_creation_tok,
            cost,
        ) in rows
    ]


def _get_usage_export_query(
    start: datetime,
    end: datetime,
    model: str | None = None,
) -> Any:
    utc_day = func.date(func.timezone("UTC", UserUsage.window_start))
    # Deleted users/API keys leave user_id NULL but keep their spend. An inner
    # join would hide that spend here while the tenant-wide totals still count
    # it, so the export would silently stop reconciling with them.
    email_label = func.coalesce(User.email, DELETED_USER_EXPORT_EMAIL)
    query = (
        select(
            email_label,
            UserUsage.model,
            UserUsage.flow,
            UserUsage.provider,
            UserUsage.incognito,
            utc_day.label("day"),
            func.sum(UserUsage.input_tokens),
            func.sum(UserUsage.output_tokens),
            func.sum(UserUsage.cache_read_tokens),
            func.sum(UserUsage.cache_creation_tokens),
            func.sum(UserUsage.cost_cents),
        )
        # UserUsage.user_id on the left: User.id comes from the fastapi-users
        # base, which ty resolves as a plain value rather than a column.
        .outerjoin(User, UserUsage.user_id == User.id)
        .where(
            UserUsage.actor_kind == UsageActorKind.USER,
            UserUsage.window_start >= start,
            UserUsage.window_start < end,
        )
        .group_by(
            email_label,
            UserUsage.model,
            UserUsage.flow,
            UserUsage.provider,
            UserUsage.incognito,
            utc_day,
        )
        .order_by(
            email_label,
            utc_day,
            UserUsage.model,
            UserUsage.flow,
            UserUsage.provider,
            UserUsage.incognito,
        )
    )
    if model is not None:
        query = query.where(UserUsage.model == model)

    return query


def iter_usage_export(
    db_session: Session,
    start: datetime,
    end: datetime,
    model: str | None = None,
) -> Iterator[UsageExportRow]:
    result = db_session.execute(
        _get_usage_export_query(start, end, model).execution_options(
            stream_results=True
        )
    ).yield_per(1000)
    for (
        email,
        mdl,
        flow,
        provider,
        incognito,
        day,
        in_tok,
        out_tok,
        cache_read_tok,
        cache_creation_tok,
        cost,
    ) in result:
        yield UsageExportRow(
            email=str(email),
            model=mdl,
            flow=flow,
            provider=provider,
            incognito=bool(incognito),
            day=str(day),
            input_tokens=int(in_tok or 0),
            output_tokens=int(out_tok or 0),
            cache_read_tokens=int(cache_read_tok or 0),
            cache_creation_tokens=int(cache_creation_tok or 0),
            cost_cents=float(cost or 0.0),
        )


def get_usage_export(
    db_session: Session,
    start: datetime,
    end: datetime,
    model: str | None = None,
) -> list[UsageExportRow]:
    return list(iter_usage_export(db_session, start, end, model))


def get_usage_reset_window_start(
    now: datetime, rate_limits: Sequence[TokenRateLimit]
) -> datetime:
    """Return the earliest bucket included by any applicable limit."""
    return min(
        [
            get_window_start(now, USER_USAGE_BUCKET_SECONDS),
            *(get_period_window_start(now, limit.period) for limit in rate_limits),
        ]
    )


def reset_user_usage(db_session: Session, user_id: str, window_start: datetime) -> int:
    """Clear a user's usage within the active enforcement window."""
    result = cast(
        CursorResult[Any],
        db_session.execute(
            delete(UserUsage).where(
                UserUsage.user_id == user_id,
                UserUsage.window_start >= window_start,
            )
        ),
    )
    db_session.flush()
    return result.rowcount or 0


def get_user_cost_cents_in_window(
    db_session: Session,
    user_id: str,
    window_start: datetime,
) -> float:
    """Exact-window total for display; enforcement uses get_user_cost_cents_since."""
    total = db_session.execute(
        select(func.coalesce(func.sum(UserUsage.cost_cents), 0.0)).where(
            UserUsage.user_id == user_id,
            UserUsage.window_start == window_start,
        )
    ).scalar_one()
    return float(total)


def get_user_cost_cents_since(
    db_session: Session,
    user_id: str,
    cutoff: datetime,
) -> float:
    """Sliding cost: sum rows with window_start >= cutoff
    (fixed grid → range scan, not exact-window match)."""
    total = db_session.execute(
        select(func.coalesce(func.sum(UserUsage.cost_cents), 0.0)).where(
            UserUsage.user_id == user_id,
            UserUsage.window_start >= cutoff,
        )
    ).scalar_one()
    return float(total)


def get_user_cost_cents_buckets_since(
    db_session: Session,
    user_id: str,
    cutoff: datetime,
) -> list[tuple[datetime, float]]:
    """Per-window cost buckets for one user — Python-side multi-period windowing."""
    rows = db_session.execute(
        select(
            UserUsage.window_start,
            func.coalesce(func.sum(UserUsage.cost_cents), 0.0),
        )
        .where(
            UserUsage.user_id == user_id,
            UserUsage.window_start >= cutoff,
        )
        .group_by(UserUsage.window_start)
    ).all()
    return [(datetime_to_utc(window_start), float(cost)) for window_start, cost in rows]


def get_total_cost_cents_since(
    db_session: Session,
    cutoff: datetime,
) -> float:
    """Tenant-wide cost (cents) in ledger windows >= `cutoff` — global cost budgets."""
    total = db_session.execute(
        select(func.coalesce(func.sum(UserUsage.cost_cents), 0.0)).where(
            UserUsage.window_start >= cutoff,
        )
    ).scalar_one()
    return float(total)


def get_total_cost_cents_buckets_since(
    db_session: Session,
    cutoff: datetime,
) -> list[tuple[datetime, float]]:
    """Tenant-wide per-window cost buckets for multi-period global budgets."""
    rows = db_session.execute(
        select(
            UserUsage.window_start,
            func.coalesce(func.sum(UserUsage.cost_cents), 0.0),
        )
        .where(UserUsage.window_start >= cutoff)
        .group_by(UserUsage.window_start)
    ).all()
    return [(datetime_to_utc(window_start), float(cost)) for window_start, cost in rows]


def get_group_cost_cents_since(
    db_session: Session,
    user_group_id: int,
    cutoff: datetime,
) -> float:
    """Cost (cents) accrued by a group's members in ledger windows >= `cutoff`."""
    total = db_session.execute(
        select(func.coalesce(func.sum(UserUsage.cost_cents), 0.0))
        .join(User__UserGroup, User__UserGroup.user_id == UserUsage.user_id)
        .where(
            User__UserGroup.user_group_id == user_group_id,
            UserUsage.window_start >= cutoff,
        )
    ).scalar_one()
    return float(total)


def get_group_cost_cents_buckets_since(
    db_session: Session,
    user_group_ids: list[int],
    cutoff: datetime,
) -> dict[int, list[tuple[datetime, float]]]:
    """Per-group (window_start, cents) buckets in one query for Python windowing."""
    rows = db_session.execute(
        select(
            User__UserGroup.user_group_id,
            UserUsage.window_start,
            func.coalesce(func.sum(UserUsage.cost_cents), 0.0),
        )
        .join(User__UserGroup, User__UserGroup.user_id == UserUsage.user_id)
        .where(
            User__UserGroup.user_group_id.in_(user_group_ids),
            UserUsage.window_start >= cutoff,
        )
        .group_by(User__UserGroup.user_group_id, UserUsage.window_start)
    ).all()

    result: dict[int, list[tuple[datetime, float]]] = defaultdict(list)
    for group_id, window_start, cost in rows:
        result[group_id].append((datetime_to_utc(window_start), float(cost)))
    return result


def get_user_token_buckets_since(
    db_session: Session,
    user_id: str,
    cutoff: datetime,
) -> list[TokenUsageBucket]:
    """Provider input + output tokens across all recorded flows for one user."""
    rows = db_session.execute(
        select(
            UserUsage.window_start,
            func.sum(UserUsage.input_tokens + UserUsage.output_tokens),
        )
        .where(UserUsage.user_id == user_id, UserUsage.window_start >= cutoff)
        .group_by(UserUsage.window_start)
        .order_by(UserUsage.window_start)
    ).all()
    return [
        TokenUsageBucket(window_start=datetime_to_utc(window_start), tokens=int(tokens))
        for window_start, tokens in rows
    ]


def get_total_token_buckets_since(
    db_session: Session,
    cutoff: datetime,
) -> list[TokenUsageBucket]:
    """Tenant-wide provider input + output tokens across all recorded flows."""
    rows = db_session.execute(
        select(
            UserUsage.window_start,
            func.sum(UserUsage.input_tokens + UserUsage.output_tokens),
        )
        .where(UserUsage.window_start >= cutoff)
        .group_by(UserUsage.window_start)
        .order_by(UserUsage.window_start)
    ).all()
    return [
        TokenUsageBucket(window_start=datetime_to_utc(window_start), tokens=int(tokens))
        for window_start, tokens in rows
    ]


def get_group_token_buckets_since(
    db_session: Session,
    user_group_ids: list[int],
    cutoff: datetime,
) -> dict[int, list[TokenUsageBucket]]:
    """Provider input + output tokens across all recorded flows per group."""
    rows = db_session.execute(
        select(
            User__UserGroup.user_group_id,
            UserUsage.window_start,
            func.sum(UserUsage.input_tokens + UserUsage.output_tokens),
        )
        .join(User__UserGroup, User__UserGroup.user_id == UserUsage.user_id)
        .where(
            User__UserGroup.user_group_id.in_(user_group_ids),
            UserUsage.window_start >= cutoff,
        )
        .group_by(User__UserGroup.user_group_id, UserUsage.window_start)
        .order_by(User__UserGroup.user_group_id, UserUsage.window_start)
    ).all()

    result: dict[int, list[TokenUsageBucket]] = defaultdict(list)
    for group_id, window_start, tokens in rows:
        result[group_id].append(
            TokenUsageBucket(
                window_start=datetime_to_utc(window_start), tokens=int(tokens)
            )
        )
    return result
