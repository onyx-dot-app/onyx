from typing import Annotated

from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeDirection,
    ScopeInclude,
    ScopeOpaque,
    ScopeToggle,
)
from onyx.connectors.microsoft_utils.config import MicrosoftCloudBinding
from onyx.connectors.planning_rule import ConnectorChangeOverride

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

_MEETING_ORGANIZERS = "meeting_organizers"
# Files, transcripts and meeting chats are documents of their own.
_DOCUMENT_TYPE_TOGGLE = FieldPolicy(
    FieldClass.SCOPE, scope=ScopeToggle(widens_when=True)
)


class TeamsConnectorConfig(MicrosoftCloudBinding, ConnectorConfig):
    teams: Annotated[
        list[str] | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
    max_workers: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = MAX_WORKERS
    include_attachments: Annotated[bool, _DOCUMENT_TYPE_TOGGLE] = False
    # Adds image sections to thread and meeting chat documents.
    include_inline_images: Annotated[bool, FieldPolicy(FieldClass.BEHAVIOR)] = False
    include_meeting_transcripts: Annotated[bool, _DOCUMENT_TYPE_TOGGLE] = False
    meeting_organizers: Annotated[
        list[str] | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
    # Legacy key, read only while meeting_organizers is empty.
    transcript_organizers: Annotated[
        list[str] | None, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())
    ] = None
    include_meeting_chats: Annotated[bool, _DOCUMENT_TYPE_TOGGLE] = False


def teams_planning_rule(
    old: TeamsConnectorConfig, new: TeamsConnectorConfig
) -> ConnectorChangeOverride | None:
    # With the legacy key set, an empty meeting_organizers falls back to it
    # instead of meaning every organizer.
    if old.transcript_organizers or new.transcript_organizers:
        return ConnectorChangeOverride(
            scope_directions={_MEETING_ORGANIZERS: ScopeDirection.UNKNOWN}
        )
    return None
