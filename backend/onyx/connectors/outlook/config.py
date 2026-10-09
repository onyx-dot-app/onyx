from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.microsoft_utils.config import MicrosoftCloudBinding

# The calendar view needs explicit bounds. Past meetings hold the decisions
# people search for, so the window reaches further back than ahead. Pruning
# lists over the same window, so the index holds a rolling calendar.
DEFAULT_CALENDAR_PAST_DAYS = 365
DEFAULT_CALENDAR_FUTURE_DAYS = 180


class OutlookConnectorConfig(MicrosoftCloudBinding, ConnectorConfig):
    mailboxes: list[str] | None = None
    mailbox_groups: list[str] | None = None
    excluded_folders: list[str] | None = None
    include_attachments: bool = False
    include_calendar: bool = False
    calendar_past_days: int = DEFAULT_CALENDAR_PAST_DAYS
    calendar_future_days: int = DEFAULT_CALENDAR_FUTURE_DAYS
    batch_size: int = INDEX_BATCH_SIZE
