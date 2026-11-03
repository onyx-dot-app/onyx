"""Daily per-user LLM usage rollup for cost/token attribution.

A window rollup: rows accumulate in place per (user, window,
model, flow, provider, incognito), not an append-only per-call ledger."""

from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from datetime import datetime, timedelta
from typing import Any, cast

from pydantic import BaseModel
from sqlalchemy import delete, func, insert, literal, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine.cursor import CursorResult
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from onyx.configs.constants import TokenRateLimitPeriod
from onyx.db.enums import UsageActorKind
from onyx.db.llm_usage import LLMUsageRecord, build_usage_upsert_values
from onyx.db.models import (
    USAGE_MODEL_CONFIGURATION_KEY,
    TokenRateLimit,
    TokenRateLimitUsageBaseline,
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


def get_usage_bucket_start(dt: datetime) -> datetime:
    return get_window_start(dt, USER_USAGE_BUCKET_SECONDS)


def _reset_bucket_in_period(
    now: datetime, period: TokenRateLimitPeriod, usage_reset_at: datetime | None
) -> datetime | None:
    """The bucket that holds the limit's usage reset, when the reset is in the
    current period."""
    if usage_reset_at is None:
        return None
    reset_bucket = get_usage_bucket_start(usage_reset_at)
    return (
        reset_bucket if reset_bucket >= get_period_window_start(now, period) else None
    )


def get_limit_usage_start(
    now: datetime, period: TokenRateLimitPeriod, usage_reset_at: datetime | None
) -> datetime:
    """Earliest bucket that counts toward a limit: its current period's start,
    or the bucket of a usage reset in the period."""
    return _reset_bucket_in_period(
        now, period, usage_reset_at
    ) or get_period_window_start(now, period)


def sum_limit_usage(
    buckets: Iterable[tuple[datetime, float]],
    now: datetime,
    period: TokenRateLimitPeriod,
    usage_reset_at: datetime | None,
    baseline: float,
) -> float:
    """Usage that counts toward a limit this period. After a reset, the reset
    day's bucket counts only what it gained since the reset: `baseline` is
    what it held at the reset."""
    start = get_limit_usage_start(now, period, usage_reset_at)
    reset_bucket = _reset_bucket_in_period(now, period, usage_reset_at)
    used = 0.0
    reset_day = 0.0
    for bucket_start, amount in buckets:
        if bucket_start < start:
            continue
        if bucket_start == reset_bucket:
            reset_day += amount
        else:
            used += amount
    if reset_bucket is None:
        return used + reset_day
    return used + max(0.0, reset_day - baseline)


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
    """Earliest usage start across the limits, so one fetch covers every window."""
    return min(
        get_limit_usage_start(now, limit.period, limit.usage_reset_at)
        for limit in rate_limits
    )


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
    """Clear a user's usage within the active enforcement window, with the
    user's limit-reset baselines for buckets in it: a baseline must not be
    subtracted again from usage that is gone."""
    reset_in_window = select(TokenRateLimit.id).where(
        TokenRateLimit.usage_reset_at >= window_start
    )
    db_session.execute(
        delete(TokenRateLimitUsageBaseline).where(
            TokenRateLimitUsageBaseline.user_id == user_id,
            TokenRateLimitUsageBaseline.token_rate_limit_id.in_(reset_in_window),
        )
    )
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


def _model_clause(model_configuration_id: int | None) -> list[ColumnElement[bool]]:
    """No filter for None: all-models limits count usage of every model."""
    if model_configuration_id is None:
        return []
    return [UserUsage.model_configuration_id == model_configuration_id]


def get_user_cost_cents_buckets_since(
    db_session: Session,
    user_id: str,
    cutoff: datetime,
    model_configuration_id: int | None = None,
) -> list[tuple[datetime, float]]:
    """Per-window cost buckets for one user — Python-side multi-period windowing."""
    rows = db_session.execute(
        select(
            UserUsage.window_start,
            func.coalesce(func.sum(UserUsage.cost_cents), 0.0),
        )
        .where(
            *_model_clause(model_configuration_id),
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
    model_configuration_id: int | None = None,
) -> list[tuple[datetime, float]]:
    """Tenant-wide per-window cost buckets for multi-period global budgets."""
    rows = db_session.execute(
        select(
            UserUsage.window_start,
            func.coalesce(func.sum(UserUsage.cost_cents), 0.0),
        )
        .where(*_model_clause(model_configuration_id), UserUsage.window_start >= cutoff)
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
    model_configuration_id: int | None = None,
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
            *_model_clause(model_configuration_id),
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
    model_configuration_id: int | None = None,
) -> list[TokenUsageBucket]:
    """Provider input + output tokens across all recorded flows for one user."""
    rows = db_session.execute(
        select(
            UserUsage.window_start,
            func.sum(UserUsage.input_tokens + UserUsage.output_tokens),
        )
        .where(
            *_model_clause(model_configuration_id),
            UserUsage.user_id == user_id,
            UserUsage.window_start >= cutoff,
        )
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
    model_configuration_id: int | None = None,
) -> list[TokenUsageBucket]:
    """Tenant-wide provider input + output tokens across all recorded flows."""
    rows = db_session.execute(
        select(
            UserUsage.window_start,
            func.sum(UserUsage.input_tokens + UserUsage.output_tokens),
        )
        .where(*_model_clause(model_configuration_id), UserUsage.window_start >= cutoff)
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
    model_configuration_id: int | None = None,
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
            *_model_clause(model_configuration_id),
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


class PoolUsageBuckets(BaseModel):
    tokens: list[tuple[datetime, float]]
    cost_cents: list[tuple[datetime, float]]


def get_pool_usage_buckets_since(
    db_session: Session,
    cutoff: datetime,
    model_configuration_id: int | None,
    user_group_id: int | None,
) -> PoolUsageBuckets:
    """Per-bucket usage of the workspace pool, or of one group's pool."""
    if user_group_id is None:
        token_rows = get_total_token_buckets_since(
            db_session, cutoff, model_configuration_id
        )
        cost = get_total_cost_cents_buckets_since(
            db_session, cutoff, model_configuration_id
        )
    else:
        token_rows = get_group_token_buckets_since(
            db_session, [user_group_id], cutoff, model_configuration_id
        ).get(user_group_id, [])
        cost = get_group_cost_cents_buckets_since(
            db_session, [user_group_id], cutoff, model_configuration_id
        ).get(user_group_id, [])
    return PoolUsageBuckets(
        tokens=[(bucket.window_start, float(bucket.tokens)) for bucket in token_rows],
        cost_cents=cost,
    )


def insert_user_usage_baselines__no_commit(
    db_session: Session,
    token_rate_limit_id: int,
    bucket_start: datetime,
    model_configuration_id: int | None,
) -> None:
    """Store every user's usage in one bucket as the limit's reset baselines.
    Every user, not only those the limit covers now: one who joins a group
    later still has their pre-reset usage subtracted."""
    query = (
        select(
            literal(token_rate_limit_id),
            UserUsage.user_id,
            func.sum(UserUsage.input_tokens + UserUsage.output_tokens),
            func.coalesce(func.sum(UserUsage.cost_cents), 0.0),
        )
        .where(
            *_model_clause(model_configuration_id),
            UserUsage.window_start == bucket_start,
            UserUsage.user_id.is_not(None),
        )
        .group_by(UserUsage.user_id)
    )
    db_session.execute(
        insert(TokenRateLimitUsageBaseline).from_select(
            [
                TokenRateLimitUsageBaseline.token_rate_limit_id,
                TokenRateLimitUsageBaseline.user_id,
                TokenRateLimitUsageBaseline.tokens,
                TokenRateLimitUsageBaseline.cost_cents,
            ],
            query,
        )
    )
