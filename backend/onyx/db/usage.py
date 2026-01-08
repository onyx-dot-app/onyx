"""Database interactions for tenant usage tracking (cloud usage limits)."""

from datetime import datetime
from datetime import timezone
from enum import Enum

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from onyx.db.models import TenantUsage
from onyx.utils.logger import setup_logger
from shared_configs.configs import USAGE_LIMIT_WINDOW_SECONDS

logger = setup_logger()


class UsageType(str, Enum):
    """Types of usage that can be tracked and limited."""

    LLM_COST = "llm_cost_cents"
    CHUNKS_INDEXED = "chunks_indexed"
    API_CALLS = "api_calls"
    NON_STREAMING_API_CALLS = "non_streaming_api_calls"


class TenantUsageStats(BaseModel):
    """Current usage statistics for a tenant."""

    window_start: datetime
    llm_cost_cents: float
    chunks_indexed: int
    api_calls: int
    non_streaming_api_calls: int


class UsageLimitExceededError(Exception):
    """Raised when a tenant exceeds their usage limit."""

    def __init__(self, usage_type: UsageType, current: float, limit: float):
        self.usage_type = usage_type
        self.current = current
        self.limit = limit
        super().__init__(
            f"Usage limit exceeded for {usage_type.value}: "
            f"current usage {current}, limit {limit}"
        )


def get_current_window_start() -> datetime:
    """
    Calculate the start of the current usage window.

    Uses fixed windows aligned to Monday 00:00 UTC for predictability.
    The window duration is configured via USAGE_LIMIT_WINDOW_SECONDS.
    """
    now = datetime.now(timezone.utc)
    # For weekly windows (default), align to Monday 00:00 UTC
    if USAGE_LIMIT_WINDOW_SECONDS == 604800:  # 1 week
        # Get the start of the current week (Monday)
        days_since_monday = now.weekday()
        window_start = now.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - __import__("datetime").timedelta(days=days_since_monday)
        return window_start

    # For other window sizes, use epoch-aligned windows
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    seconds_since_epoch = int((now - epoch).total_seconds())
    window_number = seconds_since_epoch // USAGE_LIMIT_WINDOW_SECONDS
    window_start_seconds = window_number * USAGE_LIMIT_WINDOW_SECONDS
    return epoch + __import__("datetime").timedelta(seconds=window_start_seconds)


def get_or_create_tenant_usage(
    db_session: Session,
    window_start: datetime | None = None,
) -> TenantUsage:
    """
    Get or create the usage record for the current window.

    Uses INSERT ... ON CONFLICT DO UPDATE to atomically create or get the record,
    avoiding TOCTOU race conditions where two concurrent requests could both
    attempt to insert a new record.
    """
    if window_start is None:
        window_start = get_current_window_start()

    # Atomic upsert: insert if not exists, or update a field to itself if exists
    # This ensures we always get back a valid row without race conditions
    stmt = (
        pg_insert(TenantUsage)
        .values(
            window_start=window_start,
            llm_cost_cents=0.0,
            chunks_indexed=0,
            api_calls=0,
            non_streaming_api_calls=0,
        )
        .on_conflict_do_update(
            index_elements=["window_start"],
            # No-op update: just set a field to its current value
            # This ensures the row is returned even on conflict
            set_={"llm_cost_cents": TenantUsage.llm_cost_cents},
        )
        .returning(TenantUsage)
    )

    result = db_session.execute(stmt).scalar_one()
    db_session.flush()

    return result


def get_tenant_usage_stats(
    db_session: Session,
    window_start: datetime | None = None,
) -> TenantUsageStats:
    """Get the current usage statistics for the tenant (read-only, no lock)."""
    if window_start is None:
        window_start = get_current_window_start()

    usage = db_session.execute(
        select(TenantUsage).where(TenantUsage.window_start == window_start)
    ).scalar_one_or_none()

    if usage is None:
        # No usage recorded yet for this window
        return TenantUsageStats(
            window_start=window_start,
            llm_cost_cents=0.0,
            chunks_indexed=0,
            api_calls=0,
            non_streaming_api_calls=0,
        )

    return TenantUsageStats(
        window_start=usage.window_start,
        llm_cost_cents=usage.llm_cost_cents,
        chunks_indexed=usage.chunks_indexed,
        api_calls=usage.api_calls,
        non_streaming_api_calls=usage.non_streaming_api_calls,
    )


def increment_usage(
    db_session: Session,
    usage_type: UsageType,
    amount: float | int,
) -> None:
    """
    Atomically increment a usage counter.

    Uses row-level locking to prevent race conditions.
    The caller should handle the transaction commit.
    """
    usage = get_or_create_tenant_usage(db_session)

    if usage_type == UsageType.LLM_COST:
        usage.llm_cost_cents += float(amount)
    elif usage_type == UsageType.CHUNKS_INDEXED:
        usage.chunks_indexed += int(amount)
    elif usage_type == UsageType.API_CALLS:
        usage.api_calls += int(amount)
    elif usage_type == UsageType.NON_STREAMING_API_CALLS:
        usage.non_streaming_api_calls += int(amount)

    db_session.flush()


def check_usage_limit(
    db_session: Session,
    usage_type: UsageType,
    limit: float | int,
    pending_amount: float | int = 0,
) -> None:
    """
    Check if the current usage plus pending amount would exceed the limit.

    Args:
        db_session: Database session
        usage_type: Type of usage to check
        limit: The maximum allowed usage
        pending_amount: Amount about to be used (to check before committing)

    Raises:
        UsageLimitExceededError: If usage would exceed the limit
    """
    stats = get_tenant_usage_stats(db_session)

    current_value: float
    if usage_type == UsageType.LLM_COST:
        current_value = stats.llm_cost_cents
    elif usage_type == UsageType.CHUNKS_INDEXED:
        current_value = float(stats.chunks_indexed)
    elif usage_type == UsageType.API_CALLS:
        current_value = float(stats.api_calls)
    elif usage_type == UsageType.NON_STREAMING_API_CALLS:
        current_value = float(stats.non_streaming_api_calls)
    else:
        current_value = 0.0

    if current_value + pending_amount > limit:
        raise UsageLimitExceededError(
            usage_type=usage_type,
            current=current_value + pending_amount,
            limit=float(limit),
        )
