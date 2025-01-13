from posthog import Posthog

from ee.onyx.configs.app_configs import POSTHOG_API_KEY
from ee.onyx.configs.app_configs import POSTHOG_HOST

posthog = Posthog(project_api_key=POSTHOG_API_KEY, host=POSTHOG_HOST)


def event_telemetry(
    distinct_id: str,
    event: str,
    properties: dict | None = None,
) -> None:
    posthog.capture(distinct_id, event, properties)
