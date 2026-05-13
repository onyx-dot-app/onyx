"""Pure helpers for compiling, validating, and reasoning about schedules.

Single source of truth for the cron/timezone semantics described in
``docs/craft/features/scheduled-tasks.md``:

- The DB stores a canonical 5-field cron string + IANA timezone +
  ``editor_mode`` (UI hint). All three editor modes (interval, daily/weekly,
  advanced) compile to the same cron form on save.
- ``compute_next_run_at`` returns UTC datetimes. Comparison happens in UTC;
  ``ZoneInfo`` handles DST so a "9 AM PT weekly" task stays 9 AM local
  across PST/PDT.
- Editor payloads are strictly typed via the Pydantic models below. Anything
  reaching ``compile_to_cron`` has already been validated by Pydantic at the
  HTTP boundary, so the function is a pure transformation — no
  ``dict[str, Any]`` lookups, no ad-hoc string parsing.

These functions are deliberately stateless and do NOT touch the DB. Wrap
them inside ``backend/onyx/db/scheduled_task.py`` for persisted reads/writes.
"""

from __future__ import annotations

import re
from datetime import datetime
from datetime import timezone
from typing import Literal
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from cron_descriptor import ExpressionDescriptor
from croniter import croniter
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

EditorMode = Literal["interval", "daily_weekly", "advanced"]
IntervalUnit = Literal["minutes", "hours", "days"]

# Pattern accepted from the UI's ``<input type="time">``. 24-hour, 0-23 / 0-59.
_HH_MM_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class _PayloadBase(BaseModel):
    """Common config for editor payload models — reject unknown fields."""

    model_config = ConfigDict(extra="forbid")


class IntervalPayload(_PayloadBase):
    """Validated payload for ``editor_mode == "interval"``."""

    unit: IntervalUnit
    every: int = Field(ge=1)
    # Required only when ``unit == "days"``; the model validator enforces
    # presence. Shape is enforced by ``_validate_time_of_day``.
    time_of_day: str | None = None

    @field_validator("time_of_day")
    @classmethod
    def _validate_time_of_day(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not _HH_MM_RE.match(v):
            raise ValueError("time_of_day must be in 'HH:MM' form (24-hour)")
        return v

    @model_validator(mode="after")
    def _days_requires_time_of_day(self) -> IntervalPayload:
        if self.unit == "days" and self.time_of_day is None:
            raise ValueError("time_of_day is required when unit == 'days'")
        return self


class DailyWeeklyPayload(_PayloadBase):
    """Validated payload for ``editor_mode == "daily_weekly"``.

    Weekdays follow the cron convention (0=Sunday .. 6=Saturday). An empty
    list means "every day" — equivalent to ``*`` in the weekday cron slot.
    """

    time_of_day: str
    weekdays: list[int] = Field(default_factory=list)

    @field_validator("time_of_day")
    @classmethod
    def _validate_time_of_day(cls, v: str) -> str:
        if not _HH_MM_RE.match(v):
            raise ValueError("time_of_day must be in 'HH:MM' form (24-hour)")
        return v

    @field_validator("weekdays")
    @classmethod
    def _validate_weekdays(cls, v: list[int]) -> list[int]:
        for d in v:
            if not 0 <= d <= 6:
                raise ValueError("weekdays must be ints in 0..6 (0=Sunday)")
        return v


class AdvancedPayload(_PayloadBase):
    """Validated payload for ``editor_mode == "advanced"``."""

    cron: str

    @field_validator("cron")
    @classmethod
    def _validate_cron(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("cron expression is empty")
        if len(v.split()) != 5:
            raise ValueError("cron expression must have exactly 5 fields")
        if not croniter.is_valid(v):
            raise ValueError(f"invalid cron expression: {v!r}")
        return v


EditorPayload = IntervalPayload | DailyWeeklyPayload | AdvancedPayload

# Map from the editor_mode literal to the payload model that pairs with it.
# Used by API request validators to dispatch a raw payload dict to the right
# typed model.
EDITOR_PAYLOAD_MODELS: dict[EditorMode, type[_PayloadBase]] = {
    "interval": IntervalPayload,
    "daily_weekly": DailyWeeklyPayload,
    "advanced": AdvancedPayload,
}


def validate_timezone(tz: str) -> None:
    """Raise ``OnyxError(INVALID_INPUT)`` if ``tz`` is not a valid IANA name."""
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Unknown timezone: {tz!r}",
        ) from e


def _validate_cron(cron: str) -> None:
    """Raise ``OnyxError(INVALID_INPUT)`` if ``cron`` is not a valid 5-field expression.

    Used by the read-side helpers (``compute_next_run_at``, ``next_n_fires``,
    ``human_readable``) which accept a cron string loaded from the DB.
    """
    cron = cron.strip()
    if not cron:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Cron expression is empty")
    if len(cron.split()) != 5:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Cron expression must have exactly 5 fields",
        )
    if not croniter.is_valid(cron):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, f"Invalid cron expression: {cron!r}"
        )


def _split_hh_mm(value: str) -> tuple[int, int]:
    """Split an already-validated ``HH:MM`` string into ``(hour, minute)``.

    Caller responsibility: ``value`` must have passed the ``_HH_MM_RE`` check
    on a payload model (i.e. it is non-None and well-formed).
    """
    h, m = value.split(":")
    return int(h), int(m)


def compile_to_cron(payload: EditorPayload) -> str:
    """Compile a validated editor payload into a canonical 5-field cron string.

    The payload's invariants (range bounds, ``HH:MM`` shape, required fields
    per mode) are enforced by Pydantic on construction, so this function is
    a pure transformation. Out-of-range ``every`` values for the
    sub-day units fall back to the next-coarser default (matching the
    historical behavior the UI relies on).
    """
    if isinstance(payload, AdvancedPayload):
        return payload.cron

    if isinstance(payload, IntervalPayload):
        every = payload.every
        if payload.unit == "minutes":
            # ``*/60 * * * *`` is illegal — collapse to "every hour at :00".
            if every > 59:
                return "0 * * * *"
            return f"*/{every} * * * *"
        if payload.unit == "hours":
            if every > 23:
                return "0 0 * * *"
            return f"0 */{every} * * *"
        # unit == "days" — model validator guaranteed time_of_day is set.
        assert payload.time_of_day is not None
        hour, minute = _split_hh_mm(payload.time_of_day)
        return f"{minute} {hour} */{every} * *"

    # daily_weekly
    hour, minute = _split_hh_mm(payload.time_of_day)
    weekdays = sorted(set(payload.weekdays))
    weekday_field = ",".join(str(d) for d in weekdays) if weekdays else "*"
    return f"{minute} {hour} * * {weekday_field}"


def compute_next_run_at(cron: str, tz: str, after: datetime) -> datetime:
    """Return the next UTC datetime ``cron`` fires after ``after``.

    Args:
        cron: 5-field cron expression.
        tz: IANA timezone name (used to anchor the cron schedule).
        after: Reference time. Naive datetimes are treated as UTC.

    Returns:
        Aware UTC datetime of the next fire.

    Raises:
        OnyxError(INVALID_INPUT): if ``cron``/``tz`` are invalid, or if no
            future fire exists (e.g. an impossible expression).
    """
    _validate_cron(cron)
    validate_timezone(tz)

    if after.tzinfo is None:
        after = after.replace(tzinfo=timezone.utc)

    zone = ZoneInfo(tz)
    # croniter operates in the zone supplied via the start argument.
    local_after = after.astimezone(zone)
    try:
        itr = croniter(cron, local_after)
        next_local = itr.get_next(datetime)
    except (ValueError, KeyError) as e:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Cron expression has no future fire: {cron!r} (tz={tz})",
        ) from e

    # croniter returns a naive datetime in the supplied tz on some versions;
    # ensure it's aware in `zone` and convert back to UTC.
    if next_local.tzinfo is None:
        next_local = next_local.replace(tzinfo=zone)
    return next_local.astimezone(timezone.utc)


def next_n_fires(
    cron: str,
    tz: str,
    after: datetime,
    n: int,
) -> list[datetime]:
    """Return the next ``n`` UTC fire times. Used by the UI preview endpoint.

    Raises ``OnyxError(INVALID_INPUT)`` if ``n`` is non-positive or the
    schedule is invalid.
    """
    if n <= 0:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "n must be positive")
    _validate_cron(cron)
    validate_timezone(tz)

    if after.tzinfo is None:
        after = after.replace(tzinfo=timezone.utc)

    zone = ZoneInfo(tz)
    local_after = after.astimezone(zone)
    itr = croniter(cron, local_after)
    fires: list[datetime] = []
    for _ in range(n):
        try:
            nxt = itr.get_next(datetime)
        except (ValueError, KeyError) as e:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Cron expression has no future fire: {cron!r} (tz={tz})",
            ) from e
        if nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=zone)
        fires.append(nxt.astimezone(timezone.utc))
    return fires


def human_readable(cron: str, tz: str) -> str:
    """Render a human-readable description of ``cron`` with the tz appended.

    Falls back to the raw cron expression if cron-descriptor can't render it
    (rare; cron-descriptor is permissive). The tz is always included so the
    user sees the schedule's anchor.
    """
    _validate_cron(cron)
    validate_timezone(tz)
    try:
        descriptor = ExpressionDescriptor(cron, use_24hour_time_format=False)
        text = descriptor.get_description()
    except Exception:
        text = cron
    return f"{text} ({tz})"
