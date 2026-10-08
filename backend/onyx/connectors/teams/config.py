from pydantic import Field

from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.microsoft_utils.config import MicrosoftCloudBinding

MAX_WORKERS = 10


class TeamsConnectorConfig(MicrosoftCloudBinding, ConnectorConfig):
    teams: list[str] | None = None
    max_workers: int = Field(default=MAX_WORKERS, gt=0)
    include_attachments: bool = False
    include_inline_images: bool = False
    include_meeting_transcripts: bool = False
    meeting_organizers: list[str] | None = None
    transcript_organizers: list[str] | None = None
    include_meeting_chats: bool = False
