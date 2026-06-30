"""Per-user LLM usage rollup — the source of truth for cost/token attribution.

A window-rollup like TenantUsage: rows accumulate in place per (user, window,
model, flow, provider), not an append-only per-call ledger."""

from collections import defaultdict
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserUsage
from onyx.utils.logger import setup_logger
from shared_configs.configs import USAGE_LIMIT_WINDOW_SECONDS

logger = setup_logger()

# Dimension columns that uniquely identify a ledger row within a window.
_CONFLICT_COLS = ["user_id", "window_start", "model", "flow", "provider"]

# Per-user windows coincide with the tenant-usage window. Floor at 1h so a
# sub-hour USAGE_LIMIT_WINDOW_SECONDS can't truncate to 0 (div-by-zero); windows
# finer than hourly aren't supported. Shared so the recorder and the /user/usage
# read agree on the window — a drift here would mis-bucket the displayed cost.
USAGE_PERIOD_HOURS = max(USAGE_LIMIT_WINDOW_SECONDS // 3600, 1)


def get_window_start(dt: datetime, period_hours: int) -> datetime:
    """
    Align `dt` to the start of its fixed window.

    Mirrors the tenant-usage windowing in onyx/db/usage.py so per-user and
    per-tenant windows coincide: weekly windows snap to Monday 00:00 UTC,
    other sizes use epoch-aligned windows of `period_hours`.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    # Guard against a 0/negative period producing a div-by-zero below.
    period_seconds = max(period_hours, 1) * 3600

    if period_seconds == 604800:  # 1 week — align to Monday 00:00 UTC
        midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight - timedelta(days=dt.weekday())

    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    seconds_since_epoch = int((dt - epoch).total_seconds())
    window_number = seconds_since_epoch // period_seconds
    return epoch + timedelta(seconds=window_number * period_seconds)


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
    """
    Atomically accumulate a usage sample into the per-user ledger.

    Postgres path is a single INSERT ... ON CONFLICT DO UPDATE that adds the
    new amounts to the existing row, so concurrent recorders can't lose an
    update. Caller owns the transaction commit.
    """
    # Store "" rather than NULL for a missing provider so the dedup unique index
    # collapses these rows on every Postgres version (no NULLS NOT DISTINCT).
    provider = provider or ""
    dialect = db_session.bind.dialect.name if db_session.bind is not None else ""

    if dialect == "postgresql":
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
        return

    # Non-postgres (SQLite tests): SELECT ... FOR UPDATE then add-or-insert.
    existing = db_session.execute(
        select(UserUsage)
        .where(
            UserUsage.user_id == user_id,
            UserUsage.window_start == window_start,
            UserUsage.model == model,
            UserUsage.flow == flow,
            UserUsage.provider == provider,
        )
        .with_for_update()
    ).scalar_one_or_none()

    if existing is None:
        db_session.add(
            UserUsage(
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
        )
    else:
        existing.input_tokens += input_tokens
        existing.output_tokens += output_tokens
        existing.cache_read_tokens += cache_read_tokens
        existing.cost_cents += cost_cents

    db_session.flush()


def get_user_usage_by_day_and_model(
    db_session: Session,
    user_id: str,
    since: datetime,
    until: datetime,
) -> list[dict[str, object]]:
    """
    Aggregate a user's usage by calendar day (UTC) and model over [since, until).

    Returns rows of {day, model, input_tokens, output_tokens, cache_read_tokens,
    cost_cents} sorted by (day, model).
    """
    rows = db_session.execute(
        select(
            func.date(UserUsage.window_start).label("day"),
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
        .group_by(func.date(UserUsage.window_start), UserUsage.model)
        .order_by(func.date(UserUsage.window_start), UserUsage.model)
    ).all()

    return [
        {
            "day": str(day),
            "model": model,
            "input_tokens": int(in_tok or 0),
            "output_tokens": int(out_tok or 0),
            "cache_read_tokens": int(cache_tok or 0),
            "cost_cents": float(cost or 0.0),
        }
        for day, model, in_tok, out_tok, cache_tok, cost in rows
    ]


def get_usage_export(
    db_session: Session,
    start: datetime,
    end: datetime,
    model: str | None = None,
) -> list[dict[str, object]]:
    """Tenant-wide usage joined to user email, grouped by (email, model, day).

    Covers windows whose start falls in [start, end). Day granularity follows
    the configured usage window (weekly by default), so func.date(window_start)
    is the window day, not necessarily the calendar day a call was made — a
    "daily" caller gets one row per window, labelled by that window's start day.

    Rows: {email, model, day, input_tokens, output_tokens, cache_read_tokens,
    cost_cents}, sorted by (email, day, model).
    """
    query = (
        # User.email comes from the fastapi-users base; ty mis-resolves it as a
        # non-column role, so the multi-column select overload doesn't match.
        select(  # ty: ignore[no-matching-overload]
            User.email,
            UserUsage.model,
            func.date(UserUsage.window_start).label("day"),
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
        .group_by(User.email, UserUsage.model, func.date(UserUsage.window_start))
        .order_by(User.email, func.date(UserUsage.window_start), UserUsage.model)
    )
    if model is not None:
        query = query.where(UserUsage.model == model)

    rows = db_session.execute(query).all()

    return [
        {
            "email": email,
            "model": mdl,
            "day": str(day),
            "input_tokens": int(in_tok or 0),
            "output_tokens": int(out_tok or 0),
            "cache_read_tokens": int(cache_tok or 0),
            "cost_cents": float(cost or 0.0),
        }
        for email, mdl, day, in_tok, out_tok, cache_tok, cost in rows
    ]


def reset_user_usage(db_session: Session, user_id: str) -> int:
    """Clear a user's usage for the current ledger window so an admin can lift a
    budget block before it rolls over on its own. Prior windows (the export
    history) are preserved. Returns the number of ledger rows removed."""
    window_start = get_window_start(
        datetime.now(timezone.utc), period_hours=USAGE_PERIOD_HOURS
    )
    result = db_session.execute(
        delete(UserUsage).where(
            UserUsage.user_id == user_id,
            UserUsage.window_start == window_start,
        )
    )
    db_session.commit()
    return result.rowcount or 0


def get_user_cost_cents_in_window(
    db_session: Session,
    user_id: str,
    window_start: datetime,
) -> float:
    """Total cost (cents) a user accrued in one exact ledger window — for display.

    Exact-match read against the ledger's own grid. Budget enforcement must use
    the sliding `*_since` helpers instead (see their docstrings).
    """
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
    """Cost (cents) a user accrued in ledger windows starting at/after `cutoff`.

    Sliding-window mirror of the token check: sums every ledger row whose
    window_start >= cutoff, period-agnostic. The ledger buckets on a single
    fixed grid (USAGE_LIMIT_WINDOW_SECONDS), so a range scan — not an
    exact-window match — is the only way a sub-grid budget period reads any cost.
    """
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
    """A user's cost buckets (window_start, cents) for windows >= `cutoff`, in one
    query. Batched counterpart to get_user_cost_cents_since so the per-user cost
    gate can window in Python (mirrors get_total_cost_cents_buckets_since)."""
    rows = db_session.execute(
        select(
            UserUsage.window_start,
            func.coalesce(func.sum(UserUsage.cost_cents), 0.0),
        )
        .where(UserUsage.user_id == user_id, UserUsage.window_start >= cutoff)
        .group_by(UserUsage.window_start)
    ).all()

    buckets: list[tuple[datetime, float]] = []
    for window_start, cost in rows:
        # Coerce to tz-aware UTC; SQLite returns naive datetimes.
        if window_start.tzinfo is None:
            window_start = window_start.replace(tzinfo=timezone.utc)
        buckets.append((window_start, float(cost)))
    return buckets


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
    """Tenant-wide cost buckets (window_start, cents) for windows >= `cutoff`, in
    one query. Batched counterpart to get_total_cost_cents_since so the global
    cost gate can window in Python instead of a query per limit."""
    rows = db_session.execute(
        select(
            UserUsage.window_start,
            func.coalesce(func.sum(UserUsage.cost_cents), 0.0),
        )
        .where(UserUsage.window_start >= cutoff)
        .group_by(UserUsage.window_start)
    ).all()

    buckets: list[tuple[datetime, float]] = []
    for window_start, cost in rows:
        # Coerce to tz-aware UTC; SQLite returns naive datetimes, which can't be
        # compared against the tz-aware cutoffs callers window with.
        if window_start.tzinfo is None:
            window_start = window_start.replace(tzinfo=timezone.utc)
        buckets.append((window_start, float(cost)))
    return buckets


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
    """Per-group cost buckets (window_start, cents) for windows >= `cutoff`, in
    one query. Batched counterpart to get_group_cost_cents_since so the group
    cost gate can window in Python instead of a query per group/limit."""
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
        # Coerce to tz-aware UTC; SQLite returns naive datetimes, which can't be
        # compared against the tz-aware cutoffs callers window with.
        if window_start.tzinfo is None:
            window_start = window_start.replace(tzinfo=timezone.utc)
        result[group_id].append((window_start, float(cost)))
    return result
