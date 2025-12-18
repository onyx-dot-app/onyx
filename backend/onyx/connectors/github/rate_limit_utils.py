import os
import time
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from github import Github

from onyx.utils.logger import setup_logger

logger = setup_logger()


def _load_minimum_remaining_threshold() -> int:
    """Read the configurable remaining-budget threshold from env."""
    default_threshold = 100
    try:
        return max(
            int(
                os.environ.get("GITHUB_RATE_LIMIT_MINIMUM_REMAINING", default_threshold)
            ),
            0,
        )
    except ValueError:
        return default_threshold


MINIMUM_RATE_LIMIT_REMAINING = _load_minimum_remaining_threshold()


class RateLimitBudgetLow(Exception):
    """Raised when we're close enough to the rate limit that we should pause early."""

    def __init__(
        self, remaining: int, threshold: int, reset_at: datetime, *args: object
    ) -> None:
        super().__init__(*args)
        self.remaining = remaining
        self.threshold = threshold
        self.reset_at = reset_at
        self.seconds_until_reset = max(
            0, (reset_at - datetime.now(tz=timezone.utc)).total_seconds()
        )


def raise_if_approaching_rate_limit(
    github_client: Github, minimum_remaining: int | None = None
) -> None:
    """Raise if the client is close to its rate limit to avoid long sleeps."""
    threshold = (
        minimum_remaining
        if minimum_remaining is not None
        else MINIMUM_RATE_LIMIT_REMAINING
    )
    if threshold <= 0:
        return

    core_rate_limit = github_client.get_rate_limit().core
    remaining = core_rate_limit.remaining
    # GitHub returns a naive datetime; normalize to UTC
    reset_at = core_rate_limit.reset.replace(tzinfo=timezone.utc)

    if remaining is not None and remaining <= threshold:
        raise RateLimitBudgetLow(remaining, threshold, reset_at)


def sleep_after_rate_limit_exception(github_client: Github) -> None:
    """
    Sleep until the GitHub rate limit resets.

    Args:
        github_client: The GitHub client that hit the rate limit
    """
    sleep_time = github_client.get_rate_limit().core.reset.replace(
        tzinfo=timezone.utc
    ) - datetime.now(tz=timezone.utc)
    sleep_time += timedelta(minutes=1)  # add an extra minute just to be safe
    logger.notice(f"Ran into Github rate-limit. Sleeping {sleep_time.seconds} seconds.")
    time.sleep(sleep_time.total_seconds())
