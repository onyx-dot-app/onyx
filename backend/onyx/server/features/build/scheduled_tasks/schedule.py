"""Pure helpers for compiling, validating, and reasoning about schedules.

Single source of truth for the cron/timezone semantics described in
``docs/craft/features/scheduled-tasks.md``:

- The DB stores a canonical 5-field cron string + IANA timezone +
  ``editor_mode`` (UI hint). All three editor modes (interval, daily/weekly,
  advanced) compile to the same cron form on save.
- ``compute_next_run_at`` returns UTC datetimes. Comparison happens in UTC;
  ``ZoneInfo`` handles DST so a "9 AM PT weekly" task stays 9 AM local
  across PST/PDT.

These functions are deliberately stateless and do NOT touch the DB. Wrap
them inside ``backend/onyx/db/scheduled_task.py`` for persisted reads/writes.
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from typing import Any
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from cron_descriptor import ExpressionDescriptor
from croniter import croniter

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

# Editor mode names — UI hint only. Stored verbatim on the task row.
EDITOR_MODE_INTERVAL = "interval"
EDITOR_MODE_DAILY_WEEKLY = "daily_weekly"
EDITOR_MODE_ADVANCED = "advanced"

# Interval-mode unit names.
INTERVAL_UNIT_MINUTES = "minutes"
INTERVAL_UNIT_HOURS = "hours"
INTERVAL_UNIT_DAYS = "days"

_VALID_EDITOR_MODES = frozenset(
    {EDITOR_MODE_INTERVAL, EDITOR_MODE_DAILY_WEEKLY, EDITOR_MODE_ADVANCED}
)


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
    """Raise ``OnyxError(INVALID_INPUT)`` if ``cron`` is not a valid 5-field expression."""
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


def compile_to_cron(
    editor_mode: str,
    editor_payload: dict[str, Any],
) -> str:
    """Compile a UI editor payload to a canonical 5-field cron string.

    ``editor_payload`` shape per mode:

    - ``interval``::

          {"every": int, "unit": "minutes"|"hours"|"days",
           "time_of_day": {"hour": int, "minute": int}}  # required only for unit == "days"

    - ``daily_weekly``::

          {"hour": int, "minute": int, "weekdays": list[int]}
          # weekdays follow the cron convention (0=Sunday .. 6=Saturday);
          # an empty/None list means "every day" (`* * * * *` weekday slot).

    - ``advanced``::

          {"cron": "<raw 5-field expression>"}

    Returns:
        Canonical 5-field cron string.

    Raises:
        OnyxError(INVALID_INPUT): if the editor mode is unknown or the
            payload does not produce a valid cron expression.
    """
    if editor_mode not in _VALID_EDITOR_MODES:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Unknown editor_mode {editor_mode!r}",
        )

    if editor_mode == EDITOR_MODE_ADVANCED:
        cron = str(editor_payload.get("cron", "")).strip()
        _validate_cron(cron)
        return cron

    if editor_mode == EDITOR_MODE_INTERVAL:
        every = editor_payload.get("every")
        unit = editor_payload.get("unit")
        if not isinstance(every, int) or every < 1:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "interval.every must be a positive integer",
            )
        if unit == INTERVAL_UNIT_MINUTES:
            if every > 59:
                # `*/60 * * * *` is invalid; collapse to "every hour at :00".
                cron = "0 * * * *"
            else:
                cron = f"*/{every} * * * *"
        elif unit == INTERVAL_UNIT_HOURS:
            if every > 23:
                cron = "0 0 * * *"
            else:
                cron = f"0 */{every} * * *"
        elif unit == INTERVAL_UNIT_DAYS:
            tod = editor_payload.get("time_of_day") or {}
            hour = tod.get("hour")
            minute = tod.get("minute")
            if (
                not isinstance(hour, int)
                or not 0 <= hour <= 23
                or not isinstance(minute, int)
                or not 0 <= minute <= 59
            ):
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    "interval (days) requires time_of_day.{hour,minute} in valid ranges",
                )
            cron = f"{minute} {hour} */{every} * *"
        else:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Unknown interval unit {unit!r}",
            )
        _validate_cron(cron)
        return cron

    # daily_weekly
    hour = editor_payload.get("hour")
    minute = editor_payload.get("minute")
    weekdays = editor_payload.get("weekdays") or []
    if (
        not isinstance(hour, int)
        or not 0 <= hour <= 23
        or not isinstance(minute, int)
        or not 0 <= minute <= 59
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "daily_weekly requires hour 0-23 and minute 0-59",
        )
    if not isinstance(weekdays, list) or not all(
        isinstance(d, int) and 0 <= d <= 6 for d in weekdays
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "weekdays must be a list of ints in 0..6 (0=Sunday)",
        )
    weekday_field = ",".join(str(d) for d in sorted(set(weekdays))) if weekdays else "*"
    cron = f"{minute} {hour} * * {weekday_field}"
    _validate_cron(cron)
    return cron


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
