"""Tiered license-expiry warning stage derivation.

Pure logic — no DB, no I/O. Given an `expires_at` and current time, returns the
warning stage that should drive banner copy + notification + email triggers.

Stages:
    NONE  — more than 30 days remain, or grace period already exhausted
    T_30D — 14 < days_remaining <= 30
    T_14D —  1 < days_remaining <= 14
    T_1D  —  0 < days_remaining <=  1
    GRACE — license already expired, within 14-day grace window
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from enum import Enum

LICENSE_GRACE_PERIOD_DAYS = 14


class ExpiryWarningStage(str, Enum):
    NONE = "none"
    T_30D = "t_30d"
    T_14D = "t_14d"
    T_1D = "t_1d"
    GRACE = "grace"


def get_expiry_warning_stage(expires_at: datetime) -> ExpiryWarningStage:
    seconds_remaining = (expires_at - datetime.now(timezone.utc)).total_seconds()
    days_remaining = seconds_remaining / 86400.0

    if days_remaining > 30:
        return ExpiryWarningStage.NONE
    if days_remaining > 14:
        return ExpiryWarningStage.T_30D
    if days_remaining > 1:
        return ExpiryWarningStage.T_14D
    if days_remaining > 0:
        return ExpiryWarningStage.T_1D
    if days_remaining > -LICENSE_GRACE_PERIOD_DAYS:
        return ExpiryWarningStage.GRACE
    return ExpiryWarningStage.NONE


def get_grace_period_end(expires_at: datetime) -> datetime:
    return expires_at + timedelta(days=LICENSE_GRACE_PERIOD_DAYS)


def get_grace_days_remaining(expires_at: datetime) -> int:
    grace_end_date = get_grace_period_end(expires_at).date()
    today = datetime.now(timezone.utc).date()
    return max(0, (grace_end_date - today).days)
