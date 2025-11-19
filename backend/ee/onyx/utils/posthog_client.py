from typing import Any

from posthog import Posthog

from ee.onyx.configs.app_configs import POSTHOG_API_KEY
from ee.onyx.configs.app_configs import POSTHOG_HOST
from onyx.utils.logger import setup_logger

logger = setup_logger()


def posthog_on_error(error: Any, items: Any) -> None:
    """Log any PostHog delivery errors."""
    logger.error(f"PostHog error: {error}, items: {items}")


posthog = Posthog(
    project_api_key=POSTHOG_API_KEY,
    host=POSTHOG_HOST,
    debug=True,
    on_error=posthog_on_error,
)
