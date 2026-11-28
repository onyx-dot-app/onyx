import time
from datetime import datetime, timedelta, timezone

from onyx.connectors.cross_connector_utils.server_wait import bound_server_wait
from onyx.connectors.github.source_operations import GitHubSourceOperations
from onyx.utils.logger import setup_logger

logger = setup_logger()


def sleep_after_rate_limit_exception(source_operations: GitHubSourceOperations) -> None:
    """
    Sleep until the GitHub rate limit resets.

    Args:
        source_operations: The gateway whose calls hit the rate limit
    """
    sleep_time = source_operations.get_rate_limit_reset() - datetime.now(
        tz=timezone.utc
    )
    sleep_time += timedelta(minutes=1)  # add an extra minute just to be safe
    sleep_seconds = bound_server_wait(sleep_time.total_seconds(), "github")
    logger.notice("Ran into Github rate-limit. Sleeping %s seconds.", sleep_seconds)
    time.sleep(sleep_seconds)
