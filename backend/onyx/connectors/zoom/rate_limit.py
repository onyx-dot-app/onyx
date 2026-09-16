import time
from collections.abc import Callable
from enum import Enum

import requests
from pydantic import BaseModel, ConfigDict, Field

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

# This is the "per second" in the table above rather than a window size to
# tune. Widening it would leave the counts unchanged and halve the real rate.
_RATE_LIMIT_PERIOD_SECONDS = 1.0

# rate_limit_builder sleeps 2 seconds by default and doubles from there, which
# overshoots a window that always frees within one second.
_PACING_POLL_SECONDS = 0.05

# Zoom can send a Retry-After of an hour, so each sleep is capped and the
# retries run out. The checkpoint then resumes on the same occurrence.
_BASE_RETRY_SLEEP_SECONDS = 2.0
_MAX_RETRY_SLEEP_SECONDS = 60.0

# A 429 names when to come back, so it is worth waiting out. A 5xx or a silence
# is only a guess, and the run resumes from the checkpoint anyway.
_MAX_RATE_LIMIT_SLEEPS = 6
_MAX_SERVER_ERROR_SLEEPS = 4
_MAX_NO_ANSWER_SLEEPS = 4

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
    # A share of nothing divides by zero when the pacing window is worked out.
    share: float = Field(default=DEFAULT_RATE_LIMIT_SHARE, gt=0, le=1)


def _tier_calls_per_second(
    plan: ZoomPlanTier, tier: ZoomRateLimitTier, share: float
) -> float:
    return _PLAN_CALLS_PER_SECOND[plan][tier] * share


def _pacing_window(calls_per_second: float) -> tuple[int, float]:
    """The admin can ask for 1 percent, which on Pro is a fifth of a call a
    second, and rounding that up to a whole call would spend five times the
    share they asked for."""
    if calls_per_second >= 1:
        return int(calls_per_second), _RATE_LIMIT_PERIOD_SECONDS
    seconds_per_call = 1 / calls_per_second
    return 1, seconds_per_call


def _retry_sleep_seconds(
    response: requests.Response | None, sleeps_so_far: int
) -> float:
    retry_after: float | None = (
        parse_retry_after_seconds(response.headers.get("Retry-After"))
        if response is not None
        else None
    )
    if retry_after is None:
        retry_after = _BASE_RETRY_SLEEP_SECONDS * (2**sleeps_so_far)
    return min(retry_after, _MAX_RETRY_SLEEP_SECONDS)


class _RetryKind(str, Enum):
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    NO_ANSWER = "no_answer"


# These mean the exchange broke after the request was on its way. Anything else
# requests raises, such as a malformed URL, never reached Zoom.
_NO_ANSWER_ERRORS = (
    requests.ConnectionError,
    requests.Timeout,
    requests.exceptions.ChunkedEncodingError,
    requests.exceptions.ContentDecodingError,
)


_MAX_SLEEPS: dict[_RetryKind, int] = {
    _RetryKind.RATE_LIMITED: _MAX_RATE_LIMIT_SLEEPS,
    _RetryKind.SERVER_ERROR: _MAX_SERVER_ERROR_SLEEPS,
    _RetryKind.NO_ANSWER: _MAX_NO_ANSWER_SLEEPS,
}


def _retry_kind(response: requests.Response) -> _RetryKind | None:
    if response.status_code == 429:
        return _RetryKind.RATE_LIMITED
    if response.status_code >= 500:
        return _RetryKind.SERVER_ERROR
    return None


def _build_pacer(
    plan: ZoomPlanTier,
    tier: ZoomRateLimitTier,
    share: float,
) -> _Pacer:
    max_calls, period = _pacing_window(_tier_calls_per_second(plan, tier, share))

    @rate_limit_builder(
        max_calls=max_calls,
        period=period,
        sleep_time=_PACING_POLL_SECONDS,
        sleep_backoff=1.0,
    )
    def paced(send: Callable[[], requests.Response]) -> requests.Response:
        return send()

    return paced


class ZoomRateLimiter:
    """Owns when a request goes out and whether it goes out again, so that every
    attempt Zoom counts spends a slot from the same budget.

    Zoom's limit is account-wide but there is one of these per client, so it
    cannot see the customer's other integrations. Two connectors on one account
    spend twice the share.
    """

    def __init__(self, settings: ZoomRateLimitSettings) -> None:
        self._pacers: dict[ZoomRateLimitTier, _Pacer] = {
            tier: _build_pacer(settings.plan_tier, tier, settings.share)
            for tier in ZoomRateLimitTier
        }

    def _wait(
        self,
        description: str,
        tier: ZoomRateLimitTier,
        kind: _RetryKind,
        sleeps_so_far: dict[_RetryKind, int],
        response: requests.Response | None,
        reason: str,
    ) -> bool:
        """False once this kind of answer has used up its sleeps."""
        if sleeps_so_far[kind] >= _MAX_SLEEPS[kind]:
            return False

        sleep_seconds = _retry_sleep_seconds(response, sleeps_so_far[kind])
        logger.notice(
            "Zoom %s for %s (%s tier). Waiting %.1fs before retrying.",
            reason,
            description,
            tier.value,
            sleep_seconds,
        )
        time.sleep(sleep_seconds)
        sleeps_so_far[kind] += 1
        return True

    def call(
        self,
        description: str,
        tier: ZoomRateLimitTier,
        send: Callable[[], requests.Response],
    ) -> requests.Response:
        # Counted per kind of answer, so a run of server errors does not spend
        # the patience a later 429 deserves, and the other way round.
        sleeps_so_far = {kind: 0 for kind in _RetryKind}

        while True:
            try:
                response = self._pacers[tier](send)
            except _NO_ANSWER_ERRORS as e:
                if not self._wait(
                    description,
                    tier,
                    _RetryKind.NO_ANSWER,
                    sleeps_so_far,
                    None,
                    f"did not answer ({e})",
                ):
                    raise
                continue

            kind = _retry_kind(response)
            if kind is None:
                break
            if not self._wait(
                description,
                tier,
                kind,
                sleeps_so_far,
                response,
                f"answered with {response.status_code}",
            ):
                break

        # Only a 429 needs the typed error. A spent 5xx goes back as the
        # response it is, and _raise_for_zoom_error keeps Zoom's own message.
        if response.status_code == 429:
            raise ZoomRateLimitError(
                f"Zoom kept rate limiting {description} after "
                f"{_MAX_RATE_LIMIT_SLEEPS} backoffs",
                response=response,
            )
        return response
