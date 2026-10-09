from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.microsoft_utils.config import MicrosoftCloudBinding

MAX_WORKERS = 10
# Export pages answer in about a quarter second and the per-tenant cap sits
# near fifty a second, so four teams at once stay under it.
EXPORT_TEAM_WORKERS = 4
# A team's stream is grouped in memory before its threads are built. Past this
# many messages the team goes to the channel walk instead.
EXPORT_MESSAGES_CAP = 100_000
# Channels a slim-walk batch holds per worker: channels differ a lot in size,
# so the queue a batch drains should outlast its biggest channel.
CHANNEL_BATCH_PER_WORKER = 4


class TeamsConnectorConfig(MicrosoftCloudBinding, ConnectorConfig):
    teams: list[str] | None = None
    max_workers: int = MAX_WORKERS
    include_attachments: bool = False
    include_inline_images: bool = False
    include_meeting_transcripts: bool = False
    meeting_organizers: list[str] | None = None
    transcript_organizers: list[str] | None = None
    include_meeting_chats: bool = False
