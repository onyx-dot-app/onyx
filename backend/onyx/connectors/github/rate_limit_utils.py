import time
from datetime import datetime, timedelta, timezone
from typing import Any

from github import Github
from github.GithubRetry import GithubRetry
from urllib3.response import BaseHTTPResponse
from urllib3.util.retry import Retry

from onyx.connectors.cross_connector_utils.server_wait import bound_server_wait
from onyx.utils.logger import setup_logger

logger = setup_logger()


class BoundedGithubRetry(GithubRetry):
    """GithubRetry whose server-requested waits go through bound_server_wait."""

    def increment(self, *args: Any, **kwargs: Any) -> Retry:
        retry = super().increment(*args, **kwargs)
        # GithubRetry replaces get_backoff_time with a wait until the rate
        # limit resets.
        backoff = bound_server_wait(retry.get_backoff_time(), "github")
        retry.get_backoff_time = lambda: backoff  # ty: ignore[invalid-assignment]
        return retry

    def get_retry_after(self, response: BaseHTTPResponse) -> float | None:
        retry_after = super().get_retry_after(response)
        if retry_after is None:
            return None
        return bound_server_wait(retry_after, "github")


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
    sleep_seconds = bound_server_wait(sleep_time.total_seconds(), "github")
    logger.notice("Ran into Github rate-limit. Sleeping %s seconds.", sleep_seconds)
    time.sleep(sleep_seconds)
