import time
from collections.abc import Callable
from enum import Enum

import requests
from pydantic import BaseModel, ConfigDict

from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    rate_limit_builder,
)
from onyx.utils.logger import setup_logger
from onyx.utils.retry_after import parse_retry_after_seconds

logger = setup_logger()

# Sends one request, waiting first until the tier's budget allows it.
_Pacer = Callable[[Callable[[], requests.Response]], requests.Response]


class ZoomRateLimitTier(str, Enum):
    """Zoom's Heavy and Resource-Intensive tiers are the only two with a daily
    cap. This connector calls no endpoint in either, so nothing here paces
    against a daily budget."""

    LIGHT = "light"
    MEDIUM = "medium"


class ZoomPlanTier(str, Enum):
    """Do not add Enterprise: Zoom publishes one Business+ column covering
    Business, Education, Enterprise and Partner on identical numbers. Free is
    absent because listing recordings needs Pro."""

    PRO = "pro"
    BUSINESS_PLUS = "business_plus"


# https://developers.zoom.us/docs/api/rate-limits/
_PLAN_CALLS_PER_SECOND: dict[ZoomPlanTier, dict[ZoomRateLimitTier, int]] = {
    ZoomPlanTier.PRO: {
        ZoomRateLimitTier.LIGHT: 30,
        ZoomRateLimitTier.MEDIUM: 20,
    },
    ZoomPlanTier.BUSINESS_PLUS: {
        ZoomRateLimitTier.LIGHT: 80,
        ZoomRateLimitTier.MEDIUM: 60,
    },
}

_RATE_LIMIT_PERIOD_SECONDS = 1.0

# rate_limit_builder sleeps 2 seconds by default and doubles from there, which
# overshoots a window that always frees within one second.
_PACING_POLL_SECONDS = 0.05

# Zoom can send a Retry-After of an hour, so each sleep is capped and the
# retries run out. The checkpoint then resumes on the same occurrence.
_MAX_RATE_LIMIT_SLEEPS = 6
_RATE_LIMIT_BASE_SLEEP_SECONDS = 2.0
_MAX_RATE_LIMIT_SLEEP_SECONDS = 60.0

# Half, because Zoom's limit is account-wide and the customer's other
# integrations spend from the same allowance.
DEFAULT_RATE_LIMIT_SHARE = 0.5

# A percent, not a fraction: the admin form's NumberInput sets no step, so
# HTML's default of 1 marks 0.25 invalid.
MIN_RATE_LIMIT_PERCENT = 1
MAX_RATE_LIMIT_PERCENT = 100


class ZoomRateLimitError(requests.HTTPError):
    """Zoom kept answering 429 for longer than the client will wait.

    It carries the 429 response so fails_the_whole_run reads it as systemic.
    Anything that function does not recognise ends the attempt as
    COMPLETED_WITH_ERRORS, which Onyx counts as a success, so the throttled
    occurrence would never be retried.
    """


class ZoomRateLimitSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    plan_tier: ZoomPlanTier = ZoomPlanTier.PRO
    share: float = DEFAULT_RATE_LIMIT_SHARE


def _tier_calls_per_second(
    plan: ZoomPlanTier, tier: ZoomRateLimitTier, share: float
) -> int:
    """A share that rounds down to no calls would stall the pacer forever, so
    the budget never drops below one call per second."""
    return max(1, int(_PLAN_CALLS_PER_SECOND[plan][tier] * share))


def _rate_limit_sleep_seconds(response: requests.Response, sleeps_so_far: int) -> float:
    retry_after: float | None = parse_retry_after_seconds(
        response.headers.get("Retry-After")
    )
    if retry_after is None:
        retry_after = _RATE_LIMIT_BASE_SLEEP_SECONDS * (2**sleeps_so_far)
    return min(retry_after, _MAX_RATE_LIMIT_SLEEP_SECONDS)


def _build_pacer(
    plan: ZoomPlanTier,
    tier: ZoomRateLimitTier,
    share: float,
) -> _Pacer:
    @rate_limit_builder(
        max_calls=_tier_calls_per_second(plan, tier, share),
        period=_RATE_LIMIT_PERIOD_SECONDS,
        sleep_time=_PACING_POLL_SECONDS,
        sleep_backoff=1.0,
    )
    def paced(send: Callable[[], requests.Response]) -> requests.Response:
        return send()

    return paced


class ZoomRateLimiter:
    """Zoom's limit is account-wide but there is one of these per client, so it
    cannot see the customer's other integrations. Two connectors on one account
    spend twice the share.
    """

    def __init__(self, settings: ZoomRateLimitSettings) -> None:
        self._pacers: dict[ZoomRateLimitTier, _Pacer] = {
            tier: _build_pacer(settings.plan_tier, tier, settings.share)
            for tier in ZoomRateLimitTier
        }

    def call(
        self,
        description: str,
        tier: ZoomRateLimitTier,
        send: Callable[[], requests.Response],
    ) -> requests.Response:
        response = self._pacers[tier](send)

        for sleeps_so_far in range(_MAX_RATE_LIMIT_SLEEPS):
            if response.status_code != 429:
                return response

            sleep_seconds = _rate_limit_sleep_seconds(response, sleeps_so_far)
            logger.notice(
                "Zoom rate limited %s (%s tier). Waiting %.1fs before retrying.",
                description,
                tier.value,
                sleep_seconds,
            )
            time.sleep(sleep_seconds)
            response = self._pacers[tier](send)

        if response.status_code != 429:
            return response

        raise ZoomRateLimitError(
            f"Zoom kept rate limiting {description} after "
            f"{_MAX_RATE_LIMIT_SLEEPS} backoffs",
            response=response,
        )
