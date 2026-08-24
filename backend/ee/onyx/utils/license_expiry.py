"""Expiry-derived scheduling for licenses: warning stages and the reclaim window.

Pure logic, no DB and no I/O. Given an `expires_at` and the current time,
returns the warning stage driving banner copy, notifications, and emails,
whether the license is close enough to expiry to re-fetch from the control
plane, and how long to wait between those re-fetch attempts.

Stages:
    NONE  more than 30 days remain, or grace period already exhausted
    T_30D 14 < days_remaining <= 30
    T_14D  1 < days_remaining <= 14
    T_1D   0 < days_remaining <=  1
    GRACE license already expired, within the 14-day grace window

A license that runs only to the end of a trial stays at NONE until its final
few days, since the ladder above assumes a lead-up longer than a whole trial.
"""

from datetime import datetime, timedelta, timezone
from enum import Enum

LICENSE_GRACE_PERIOD_DAYS = 14

# How close a trial must be to its end before it is worth warning about.
TRIAL_WARNING_DAYS = 3

# A license inside this window (or already expired) is due for re-claim from
# the control plane.
LICENSE_RECLAIM_WINDOW = timedelta(days=7)

# A renewal replaces the license at the period end, so only the approach to it
# is worth watching closely. The rest of the window polls at the lead-up rate.
LICENSE_RECLAIM_URGENT_WINDOW = timedelta(hours=1)
LICENSE_RECLAIM_LEAD_UP_INTERVAL = timedelta(hours=6)

# Widens when no replacement arrives, so a lapsed customer is not polled hard.
LICENSE_RECLAIM_URGENT_INTERVAL = timedelta(minutes=1)
LICENSE_RECLAIM_MAX_INTERVAL = timedelta(minutes=15)

# Where doubling reaches the cap. Also bounds the shift on a Redis-read counter.
_MAX_BACKOFF_DOUBLINGS = 4


def is_license_due_for_reclaim(expires_at: datetime) -> bool:
    return expires_at - datetime.now(timezone.utc) <= LICENSE_RECLAIM_WINDOW


def is_license_reclaim_urgent(expires_at: datetime) -> bool:
    return expires_at - datetime.now(timezone.utc) <= LICENSE_RECLAIM_URGENT_WINDOW


def license_reclaim_interval(expires_at: datetime, idle_rounds: int) -> timedelta:
    """How long to wait before the next control-plane reclaim attempt.

    idle_rounds counts consecutive attempts that came back with nothing newer.
    """
    if not is_license_reclaim_urgent(expires_at):
        return LICENSE_RECLAIM_LEAD_UP_INTERVAL

    doublings = min(max(idle_rounds, 0), _MAX_BACKOFF_DOUBLINGS)
    return min(
        LICENSE_RECLAIM_URGENT_INTERVAL * (2**doublings),
        LICENSE_RECLAIM_MAX_INTERVAL,
    )


class ExpiryWarningStage(str, Enum):
    NONE = "none"
    T_30D = "t_30d"
    T_14D = "t_14d"
    T_1D = "t_1d"
    GRACE = "grace"


def get_expiry_warning_stage(
    expires_at: datetime,
    ends_with_trial: bool = False,
    self_renewing: bool = False,
) -> ExpiryWarningStage:
    seconds_remaining = (expires_at - datetime.now(timezone.utc)).total_seconds()
    days_remaining = seconds_remaining / 86400.0

    # A self-renewing license gives an admin nothing to act on before it lapses,
    # except a trial's end, which is a first charge landing. Expiry that already
    # happened still warns: it means the renewal did not arrive.
    if self_renewing and days_remaining > 0:
        near_trial_end = ends_with_trial and days_remaining <= TRIAL_WARNING_DAYS
        if not near_trial_end:
            return ExpiryWarningStage.NONE

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
