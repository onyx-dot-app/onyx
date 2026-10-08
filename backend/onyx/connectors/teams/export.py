"""Channel threads through the export API: one stream per team of every
message changed in the window, replies included, instead of a delta page per
channel and a replies call per thread. The export API answers for an app
whose message permission was approved for it, so a team step probes once and
the channel walk stays the fallback."""

from collections import defaultdict
from collections.abc import Iterator

import requests
from pydantic import BaseModel

from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorFailure, Document, EntityFailure
from onyx.connectors.teams import listing
from onyx.connectors.teams.models import ChannelRef, Message
from onyx.connectors.teams.refusals import is_permanent, status
from onyx.connectors.teams.session import TeamsSession
from onyx.connectors.teams.threads import ThreadSource
from onyx.connectors.teams.utils import (
    fetch_root_message,
    fetch_team_export,
    get_json_with_retry,
    team_export_probe_url,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Export pages answer in about a quarter second and the per-tenant cap sits
# near fifty a second, so four teams at once stay under it.
EXPORT_TEAM_WORKERS = 4
# A team's stream is grouped in memory before its threads are built. Past this
# many messages the team goes to the channel walk instead.
EXPORT_MESSAGES_CAP = 250_000
# A still-metered tenant refuses the export API with 402: a refusal, not an
# outage.
_PAYMENT_REQUIRED = 402


class TeamExport(BaseModel):
    """What one worker brings back from a team's stream."""

    items: list[Document | ConnectorFailure]
    channels: list[ChannelRef]
    # The stream was refused or too large to hold, so the channels go to the
    # channel walk.
    fell_back: bool = False


class ExportSource:
    def __init__(self, session: TeamsSession, threads: ThreadSource) -> None:
        self._session = session
        self._threads = threads

    def available(self, team_id: str) -> bool:
        """Whether the export API answers for this app. 403 or 402, or a probe
        team that is gone or locked, means the channel walk; anything else is
        an outage and raises."""
        try:
            get_json_with_retry(self._session.graph(), team_export_probe_url(team_id))
        except requests.HTTPError as e:
            if not is_permanent(e) and status(e) != _PAYMENT_REQUIRED:
                raise
            logger.info(
                "The export API is not available to this app (%s); walking channels",
                status(e),
            )
            return False
        return True

    def team(
        self, team_id: str, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> TeamExport:
        """Every thread of the team that changed in the window. A thread whose
        root was created inside the window is complete in the stream; an older
        thread that changed anywhere gets its replies from Graph, and its root
        too when the stream lacks it."""
        graph_client = self._session.graph()
        channels = listing.team_channels(graph_client, team_id)
        by_id = {channel.id: channel for channel in channels}

        threads: dict[str, list[Message]] = defaultdict(list)
        roots: dict[str, Message] = {}
        try:
            for seen, message in enumerate(
                fetch_team_export(graph_client, team_id, start, end), start=1
            ):
                if seen > EXPORT_MESSAGES_CAP:
                    logger.warning(
                        "Team %s streams more than %s messages; walking its channels",
                        team_id,
                        EXPORT_MESSAGES_CAP,
                    )
                    return TeamExport(items=[], channels=channels, fell_back=True)
                root_id = message.replyToId or message.id
                threads[root_id].append(message)
                if message.replyToId is None:
                    roots[root_id] = message
        except requests.HTTPError as e:
            # The channel walk records what each channel refuses, as it does
            # for an app without the approval.
            if not is_permanent(e):
                raise
            logger.warning(
                "Team %s refused its export stream (%s); walking its channels",
                team_id,
                status(e),
            )
            return TeamExport(items=[], channels=channels, fell_back=True)

        items: list[Document | ConnectorFailure] = []
        for root_id, messages in threads.items():
            channel = _channel_of(messages, by_id)
            if channel is None:
                items.append(
                    ConnectorFailure(
                        failed_entity=EntityFailure(entity_id=root_id),
                        failure_message=f"Thread {root_id} of team {team_id} names no channel the team lists",
                    )
                )
                continue
            items.extend(
                self._thread(channel, root_id, roots.get(root_id), messages, start)
            )
        return TeamExport(items=items, channels=channels)

    def _thread(
        self,
        channel: ChannelRef,
        root_id: str,
        root: Message | None,
        messages: list[Message],
        start: SecondsSinceUnixEpoch,
    ) -> Iterator[Document | ConnectorFailure]:
        if root is None:
            try:
                root = fetch_root_message(
                    self._session.graph(), channel.team_id, channel.id, root_id
                )
            except requests.HTTPError as e:
                if not is_permanent(e):
                    raise
                yield ConnectorFailure(
                    failed_entity=EntityFailure(entity_id=root_id),
                    failure_message=f"Could not read thread {root_id} in channel {channel.id}",
                    exception=e,
                )
                return
        # Every reply is younger than its root, so a root created inside the
        # window has every reply changed inside it in the stream too.
        replies = (
            [message for message in messages if message.id != root_id]
            if root.created_date_time.timestamp() >= start
            else None
        )
        yield from self._threads.thread(channel, root, replies, start)


def _channel_of(
    messages: list[Message], by_id: dict[str, ChannelRef]
) -> ChannelRef | None:
    for message in messages:
        identity = message.channel_identity
        if identity is not None and identity.channel_id in by_id:
            return by_id[identity.channel_id]
    return None
