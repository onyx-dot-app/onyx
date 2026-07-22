"""Daily per-user LLM usage rollup for cost/token attribution.

A window rollup: rows accumulate in place per (user, window,
model, flow, provider), not an append-only per-call ledger."""

from collections import defaultdict
from datetime import datetime, timedelta
from math import ceil

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from onyx.db.models import User, User__UserGroup, UserUsage
from onyx.utils.datetime import datetime_to_utc, get_window_start
from onyx.utils.logger import setup_logger

logger = setup_logger()

USER_USAGE_BUCKET_SECONDS = 24 * 60 * 60
USER_USAGE_BUCKET_HOURS = USER_USAGE_BUCKET_SECONDS // (60 * 60)
TOKEN_BUDGET_PERIOD_ERROR = "Token budget periods must be whole UTC days"
COST_BUDGET_PERIOD_ERROR = "Cost budget periods must be whole UTC days"
_CONFLICT_COLS = ["user_id", "window_start", "model", "flow", "provider"]


class TokenUsageBucket(BaseModel):
    window_start: datetime
    tokens: int


def normalize_token_period_hours(period_hours: int) -> int:
    """Round legacy periods up to whole UTC days."""
    return max(
        USER_USAGE_BUCKET_HOURS,
        ceil(period_hours / USER_USAGE_BUCKET_HOURS) * USER_USAGE_BUCKET_HOURS,
    )


def get_token_window_start(now: datetime, period_hours: int) -> datetime:
    period_hours = normalize_token_period_hours(period_hours)
    current_bucket = datetime_to_utc(now).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return current_bucket - timedelta(hours=period_hours - USER_USAGE_BUCKET_HOURS)


def get_cost_window_start(now: datetime, period_hours: int) -> datetime:
    """Start of the UTC-day buckets in a cost-budget window."""
    period_seconds = period_hours * 60 * 60
    if (
        period_seconds < USER_USAGE_BUCKET_SECONDS
        or period_seconds % USER_USAGE_BUCKET_SECONDS
    ):
        raise ValueError(COST_BUDGET_PERIOD_ERROR)

    current_bucket = get_window_start(now, USER_USAGE_BUCKET_SECONDS)
    return current_bucket - timedelta(
        seconds=period_seconds - USER_USAGE_BUCKET_SECONDS
    )


def get_next_usage_bucket_start(now: datetime) -> datetime:
    return get_window_start(now, USER_USAGE_BUCKET_SECONDS) + timedelta(
        seconds=USER_USAGE_BUCKET_SECONDS
    )


class UserUsageByDay(BaseModel):
    """Per-user usage aggregated by UTC calendar day and model."""

    day: str  # YYYY-MM-DD
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_cents: float


class UsageExportRow(BaseModel):
    """Tenant-wide usage row by email, model, and UTC day."""

    email: str
    model: str
    day: str  # YYYY-MM-DD
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_cents: float


def record_user_usage(
    db_session: Session,
    user_id: str,
    model: str,
    flow: str,
    provider: str | None,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cost_cents: float,
    window_start: datetime,
) -> None:
    """Atomically accumulate into the ledger (Postgres upsert). Caller commits."""
    # Store "" rather than NULL for a missing provider so the dedup unique index
    # collapses these rows on every Postgres version (no NULLS NOT DISTINCT).
    provider = provider or ""
    stmt = pg_insert(UserUsage).values(
        user_id=user_id,
        window_start=window_start,
        model=model,
        flow=flow,
        provider=provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cost_cents=cost_cents,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=_CONFLICT_COLS,
        set_={
            "input_tokens": UserUsage.input_tokens + stmt.excluded.input_tokens,
            "output_tokens": UserUsage.output_tokens + stmt.excluded.output_tokens,
            "cache_read_tokens": UserUsage.cache_read_tokens
            + stmt.excluded.cache_read_tokens,
            "cost_cents": UserUsage.cost_cents + stmt.excluded.cost_cents,
        },
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
            cache_read_tokens=int(cache_tok or 0),
            cost_cents=float(cost or 0.0),
        )
        for day, model, in_tok, out_tok, cache_tok, cost in rows
    ]


def get_usage_export(
    db_session: Session,
    start: datetime,
    end: datetime,
    model: str | None = None,
) -> list[UsageExportRow]:
    """Tenant-wide usage by email, model, and UTC day."""
    utc_day = func.date(func.timezone("UTC", UserUsage.window_start))
    query = (
        # User.email comes from the fastapi-users base; ty mis-resolves it as a
        # non-column role, so the multi-column select overload doesn't match.
        select(  # ty: ignore[no-matching-overload]
            User.email,
            UserUsage.model,
            utc_day.label("day"),
            func.sum(UserUsage.input_tokens),
            func.sum(UserUsage.output_tokens),
            func.sum(UserUsage.cache_read_tokens),
            func.sum(UserUsage.cost_cents),
        )
        .join(User, User.id == UserUsage.user_id)
        .where(
            UserUsage.window_start >= start,
            UserUsage.window_start < end,
        )
        .group_by(User.email, UserUsage.model, utc_day)
        .order_by(User.email, utc_day, UserUsage.model)
    )
    if model is not None:
        query = query.where(UserUsage.model == model)

    rows = db_session.execute(query).all()

    return [
        UsageExportRow(
            email=str(email),
            model=mdl,
            day=str(day),
            input_tokens=int(in_tok or 0),
            output_tokens=int(out_tok or 0),
            cache_read_tokens=int(cache_tok or 0),
            cost_cents=float(cost or 0.0),
        )
        for email, mdl, day, in_tok, out_tok, cache_tok, cost in rows
    ]


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
