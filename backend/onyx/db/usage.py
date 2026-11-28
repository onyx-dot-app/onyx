"""Database interactions for tenant usage tracking (cloud usage limits).

Usage is stored in ``tenant_usage_counter``: one row per usage type per
period. A period has a start, an end (or none, for a period that never ends)
and what it follows (``WindowAnchor``). The check and the add for one limit
must use the same period, or they read and write different rows.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from onyx.db.enums import UsageType, WindowAnchor
from onyx.db.models import (
    TENANT_USAGE_COUNTER_PERIOD_END_KEY,
    ChatSession,
    TenantUsageCounter,
    ToolCall,
)
from onyx.utils.datetime import get_window_start
from onyx.utils.logger import setup_logger
from shared_configs.configs import USAGE_LIMIT_WINDOW_SECONDS

logger = setup_logger()


class UsagePeriod(BaseModel):
    """One period that usage is added up in."""

    model_config = ConfigDict(frozen=True)

    anchor: WindowAnchor
    start: datetime
    # None means the period never ends.
    end: datetime | None = None

    @field_validator("start", "end")
    @classmethod
    def _in_utc(cls, value: datetime | None) -> datetime | None:
        """Times are kept in UTC, so comparing them compares real instants,
        also across a daylight saving change."""
        if value is None:
            return None
        if value.utcoffset() is None:
            raise ValueError("A usage period needs timezone-aware times")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _ends_after_start(self) -> "UsagePeriod":
        if self.end is not None and self.end <= self.start:
            raise ValueError("A usage period must end after it starts")
        return self


class UsageLimitExceededError(Exception):
    """Raised when a tenant exceeds their usage limit."""

    def __init__(self, usage_type: UsageType, current: float, limit: float):
        self.usage_type = usage_type
        self.current = current
        self.limit = limit
        super().__init__(
            f"Usage limit exceeded for {usage_type.value}: current usage {current}, limit {limit}"
        )


def current_calendar_period(now: datetime | None = None) -> UsagePeriod:
    """The calendar period that contains ``now``. With the default
    USAGE_LIMIT_WINDOW_SECONDS, the week from Monday 00:00 UTC."""
    start = get_window_start(
        now or datetime.now(timezone.utc), USAGE_LIMIT_WINDOW_SECONDS
    )
    return UsagePeriod(
        anchor=WindowAnchor.CALENDAR,
        start=start,
        end=start + timedelta(seconds=USAGE_LIMIT_WINDOW_SECONDS),
    )


def _in_period(period: UsagePeriod) -> list[ColumnElement[bool]]:
    end_matches = (
        TenantUsageCounter.window_end.is_(None)
        if period.end is None
        else TenantUsageCounter.window_end == period.end
    )
    return [
        TenantUsageCounter.window_anchor == period.anchor,
        TenantUsageCounter.window_start == period.start,
        end_matches,
    ]


def get_usage(db_session: Session, usage_type: UsageType, period: UsagePeriod) -> float:
    """How much of ``usage_type`` the tenant used in ``period``. 0 if nothing
    was added yet."""
    amount = db_session.scalar(
        select(TenantUsageCounter.amount).where(
            TenantUsageCounter.usage_type == usage_type, *_in_period(period)
        )
    )
    return amount or 0.0


def increment_usage(
    db_session: Session,
    usage_type: UsageType,
    amount: float | int,
    period: UsagePeriod | None = None,
) -> None:
    """
    Add ``amount`` to the tenant's usage of ``usage_type`` in ``period`` (the
    current calendar period if not given).

    One statement: it creates the row or adds to it, so concurrent adds are
    never lost. The caller commits.
    """
    if period is None:
        period = current_calendar_period()

    stmt = pg_insert(TenantUsageCounter).values(
        usage_type=usage_type,
        window_anchor=period.anchor,
        window_start=period.start,
        window_end=period.end,
        amount=amount,
    )
    # If this usage type already has a row for this period, add to its amount
    # instead of inserting a second row. The four elements must match the
    # unique index on the table.
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            TenantUsageCounter.usage_type,
            TenantUsageCounter.window_anchor,
            TenantUsageCounter.window_start,
            TENANT_USAGE_COUNTER_PERIOD_END_KEY,
        ],
        set_={
            "amount": TenantUsageCounter.amount + stmt.excluded.amount,
            "updated_at": func.now(),
        },
    )
    db_session.execute(stmt)


def check_usage_limit(
    db_session: Session,
    usage_type: UsageType,
    limit: float | int,
    pending_amount: float | int = 0,
    period: UsagePeriod | None = None,
) -> None:
    """
    Raise ``UsageLimitExceededError`` if the usage in ``period`` (the current
    calendar period if not given) plus ``pending_amount`` is over ``limit``.
    """
    if period is None:
        period = current_calendar_period()

    current_value = get_usage(db_session, usage_type, period)
    if current_value + pending_amount > limit:
        raise UsageLimitExceededError(
            usage_type=usage_type,
            current=current_value + pending_amount,
            limit=float(limit),
        )


def count_generated_images(db_session: Session, user_id: UUID) -> int:
    """How many images the chat image tool generated for this user, across all
    of the user's chat sessions. Each tool call stores its images, so a failed
    call counts as none. A deleted chat still counts while chats are only
    marked deleted, the default (HARD_DELETE_CHATS off)."""
    total = db_session.scalar(
        select(
            func.coalesce(
                func.sum(func.jsonb_array_length(ToolCall.generated_images)), 0
            )
        )
        .join(ChatSession, ChatSession.id == ToolCall.chat_session_id)
        .where(
            ChatSession.user_id == user_id,
            # Other tools store JSON null here, which IS NOT NULL does not skip.
            func.jsonb_typeof(ToolCall.generated_images) == "array",
        )
    )
    return int(total or 0)
