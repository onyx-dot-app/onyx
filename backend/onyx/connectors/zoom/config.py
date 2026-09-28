from pydantic import StrictFloat, StrictInt

from onyx.connectors.connector_config import ConnectorConfig


class ZoomConnectorConfig(ConnectorConfig):
    meeting_ids: list[str] | None = None
    webinar_ids: list[str] | None = None
    host_emails: list[str] | None = None
    group_id: str | None = None
    # Not ZoomPlanTier: the constructor also takes "" and any casing.
    plan_tier: str | None = None
    # Strict so a bool is not coerced to 1 percent.
    rate_limit_percent: StrictInt | StrictFloat | None = None
    include_meetings: bool | None = None
    include_webinars: bool | None = None
