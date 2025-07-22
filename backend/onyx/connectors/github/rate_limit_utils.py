import time
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from github import Github

from onyx.utils.logger import setup_logger

logger = setup_logger()


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
