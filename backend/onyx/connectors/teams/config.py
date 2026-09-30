from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.microsoft_utils.config import (
    DEFAULT_AUTHORITY_HOST,
    DEFAULT_GRAPH_API_HOST,
)

MAX_WORKERS = 10


class TeamsConnectorConfig(ConnectorConfig):
    teams: list[str] | None = None
    max_workers: int = MAX_WORKERS
    authority_host: str = DEFAULT_AUTHORITY_HOST
    graph_api_host: str = DEFAULT_GRAPH_API_HOST
    include_attachments: bool = False
    include_inline_images: bool = False
    include_meeting_transcripts: bool = False
    meeting_organizers: list[str] | None = None
    transcript_organizers: list[str] | None = None
    include_meeting_chats: bool = False
