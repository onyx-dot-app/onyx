"""Channel threads through the export API: one stream per team of every
message changed in the window, replies included, instead of a delta page per
channel and a replies call per thread. The export API answers for an app
whose message permission was approved for it, so a team step probes once and
the channel walk stays the fallback."""

import time
from collections import defaultdict
from collections.abc import Iterator

import requests
from office365.graph_client import GraphClient

from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorFailure, Document, EntityFailure
from onyx.connectors.teams import listing
from onyx.connectors.teams.config import EXPORT_MESSAGES_CAP
from onyx.connectors.teams.models import (
    ChannelIdentity,
    ChannelRef,
    Message,
    TeamExport,
)
from onyx.connectors.teams.refusals import (
    ExportProbe,
    export_probe_refusal,
    is_export_refusal,
    is_metered_refusal,
    is_permanent,
    status,
)
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


class ExportSource:
    def __init__(self, session: TeamsSession, threads: ThreadSource) -> None:
        self._session = session
        self._threads = threads

    def available(self, team_id: str) -> ExportProbe:
        """Whether the export API answers for this app, probed on one team. A
        refusal is for the app (403, 402) or for that team alone (gone,
        locked); anything else is an outage and raises."""
        try:
            get_json_with_retry(self._session.graph(), team_export_probe_url(team_id))
        except requests.HTTPError as e:
            if not is_export_refusal(e):
                raise
            logger.info(
                "The export API is not available (%s on team %s)", status(e), team_id
            )
            return export_probe_refusal(e)
        return ExportProbe.ANSWERS

    def team(
        self, team_id: str, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> Iterator[Document | ConnectorFailure | TeamExport]:
        """Every thread of the team that changed in the window, each document
        yielded as it is built so a worker holds the grouped stream and one
        document at a time, then the TeamExport that says what the team's
        channels need next. A thread whose
        root was created inside the window is complete in the stream; an older
        thread that changed anywhere gets its replies from Graph, and its root
        too when the stream lacks it. The stream runs to the time of the
        request rather than the window's end, so a reply edited while the
        attempt runs is in it, as it would be in a live replies call; the next
        window lists that reply again."""
        # The listing is an SDK query, which must run on this worker's own
        # client. The stream is direct requests on the shared one.
        channels: list[ChannelRef] = listing.team_channels(
            self._session.graph_for_thread(), team_id
        )
        by_id: dict[str, ChannelRef] = {channel.id: channel for channel in channels}
        graph_client: GraphClient = self._session.graph()

        threads: dict[str, list[Message]] = defaultdict(list)
        roots: dict[str, Message] = {}
        try:
            stream: Iterator[Message] = fetch_team_export(
                graph_client, team_id, start, max(end, time.time())
            )
            for seen, message in enumerate(stream, start=1):
                if seen > EXPORT_MESSAGES_CAP:
                    logger.warning(
                        "Team %s streams more than %s messages; walking its channels",
                        team_id,
                        EXPORT_MESSAGES_CAP,
                    )
                    yield TeamExport(channels=channels, fell_back=True)
                    return
                root_id: str = message.replyToId or message.id
                threads[root_id].append(message)
                if message.replyToId is None:
                    roots[root_id] = message
        except requests.HTTPError as e:
            # The channel walk records what each channel refuses, as it does
            # for an app without the approval.
            if not is_export_refusal(e):
                raise
            logger.warning(
                "Team %s refused its export stream (%s); walking its channels",
                team_id,
                status(e),
            )
            yield TeamExport(
                channels=channels,
                fell_back=True,
                refused_to_app=is_metered_refusal(e),
            )
            return

        streamed: set[str] = _streamed(threads)
        quiet: list[str] = [
            channel.id for channel in channels if channel.id not in streamed
        ]
        if quiet:
            logger.debug(
                "Team %s: %s of %s listed channel(s) have no row in the stream: %s",
                team_id,
                len(quiet),
                len(channels),
                quiet,
            )
        for root_id, messages in threads.items():
            channel: ChannelRef | None = _channel_of(messages, by_id)
            if channel is None:
                yield ConnectorFailure(
                    failed_entity=EntityFailure(entity_id=root_id),
                    failure_message=f"Thread {root_id} of team {team_id} names no channel the team lists",
                )
                continue
            yield from self._thread(
                channel, root_id, roots.get(root_id), messages, start
            )
        yield TeamExport(channels=channels)

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
        replies: list[Message] | None = (
            [message for message in messages if message.id != root_id]
            if root.created_date_time.timestamp() >= start
            else None
        )
        yield from self._threads.thread(channel, root, replies, start)


def _streamed(threads: dict[str, list[Message]]) -> set[str]:
    """The channels the stream carried rows for."""
    return {
        identity.channel_id
        for messages in threads.values()
        for message in messages
        if (identity := message.channel_identity) is not None
        and identity.channel_id is not None
    }


def _channel_of(
    messages: list[Message], by_id: dict[str, ChannelRef]
) -> ChannelRef | None:
    for message in messages:
        identity: ChannelIdentity | None = message.channel_identity
        if identity is not None and identity.channel_id in by_id:
            return by_id[identity.channel_id]
    return None
