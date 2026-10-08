import copy
import os
from collections.abc import Iterator
from datetime import datetime, timezone
from itertools import chain
from typing import Any, cast

import requests
from office365.runtime.client_request_exception import ClientRequestException
from office365.sharepoint.client_context import ClientContext

from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.interfaces import (
    CheckpointedConnectorWithPermSync,
    CheckpointOutput,
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
    SlimConnector,
    SlimConnectorWithPermSync,
)
from onyx.connectors.microsoft_utils.config import (
    DEFAULT_AUTHORITY_HOST,
    DEFAULT_GRAPH_API_HOST,
)
from onyx.connectors.models import (
    ConnectorCheckpoint,
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    SlimDocument,
)
from onyx.connectors.teams import groups, listing, threads
from onyx.connectors.teams.config import (
    CHANNEL_BATCH_PER_WORKER,
    EXPORT_TEAM_WORKERS,
    MAX_WORKERS,
)
from onyx.connectors.teams.export import ExportSource
from onyx.connectors.teams.files import FileSource
from onyx.connectors.teams.meeting_chats import (
    ChatSource,
)
from onyx.connectors.teams.models import (
    ChannelAdvance,
    ChannelCursor,
    ChannelRef,
    TeamExport,
)
from onyx.connectors.teams.organizers import (
    Organizer,
    OrganizerSource,
    OrganizerStage,
)
from onyx.connectors.teams.refusals import (
    ExportProbe,
    channel_failure,
    is_permanent,
    status,
)
from onyx.connectors.teams.session import TeamsSession
from onyx.connectors.teams.sources import SlimWalk
from onyx.connectors.teams.threads import ThreadSource
from onyx.connectors.teams.transcripts import (
    TranscriptSource,
)
from onyx.connectors.teams.utils import ChannelFilesUnavailable
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.batching import batch_generator
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import (
    drain,
    run_functions_tuples_in_parallel,
    run_with_timeout,
)

logger = setup_logger()

_SLIM_DOC_BATCH_SIZE = 5000

# Every content type Graph lists per meeting organizer.
ORGANIZER_SOURCE_TYPES: tuple[type[OrganizerSource], ...] = (
    TranscriptSource,
    ChatSource,
)

# What the ids of every content type but threads start with.
PREFIXED_DOCUMENT_ID_PREFIXES = (
    FileSource.document_id_prefix,
    *(source.document_id_prefix for source in ORGANIZER_SOURCE_TYPES),
)


def is_thread_document_id(document_id: str) -> bool:
    return threads.is_thread_document_id(document_id, PREFIXED_DOCUMENT_ID_PREFIXES)


class TeamsCheckpoint(ConnectorCheckpoint):
    # None until the teams are listed.
    todo_team_ids: list[str] | None = None
    todo_channels: list[ChannelRef] = []
    # A step walks one page of each active channel, side by side, so a resumed
    # attempt loses at most a page per channel instead of a whole team.
    active: list[ChannelCursor] = []
    # Written by v4.9, which walked one channel at a time. Such a checkpoint
    # joins ``active`` when it is loaded.
    # TODO(nmgarza5): drop both once v4.9 checkpoints have aged out.
    current_channel: ChannelRef | None = None
    next_messages_url: str | None = None
    # Whether the export API answers for this app, decided at the first team
    # step and kept so every step of the attempt takes the same path.
    export: bool | None = None
    # The meeting organizers follow the channels. None until their first page is
    # listed, then a batch of organizers per step and a page at a time. Whole
    # organizers ride along, not ids: the documents name the organizer, and a
    # resumed attempt would otherwise read every user again. A page is 100.
    todo_organizers: list[Organizer] | None = None
    next_organizers_url: str | None = None


class TeamsConnector(
    TeamsSession,
    CheckpointedConnectorWithPermSync[TeamsCheckpoint],
    SlimConnector,
    SlimConnectorWithPermSync,
):
    """Walks the teams, then each team's channels a page at a time. What a
    channel holds is read by one source per content type: its threads, and its
    files when attachments are on. What a scheduled meeting leaves behind is
    listed per organizer, so those sources follow the channels."""

    def __init__(
        self,
        # TODO: (chris) move from "Display Names" to IDs, since display names
        # are not necessarily guaranteed to be unique
        teams: list[str] | None = None,
        max_workers: int = MAX_WORKERS,
        authority_host: str = DEFAULT_AUTHORITY_HOST,
        graph_api_host: str = DEFAULT_GRAPH_API_HOST,
        # Off by default: a channel file's readers come from SharePoint REST,
        # which needs a certificate credential and a sites grant.
        include_attachments: bool = False,
        # Off by default: every pasted image is a download and a vision call.
        include_inline_images: bool = False,
        # Off by default: transcripts need three more grants, a tenant setting
        # and an application access policy. Empty organizers means every
        # enabled user with a Teams license.
        include_meeting_transcripts: bool = False,
        meeting_organizers: list[str] | None = None,
        # The key a connector saved before the option covered chats too.
        transcript_organizers: list[str] | None = None,
        # Off by default: a meeting's chat needs Chat.Read.All. Walked through
        # the same organizers as the transcripts.
        include_meeting_chats: bool = False,
    ) -> None:
        TeamsSession.__init__(self, graph_api_host, authority_host)
        if max_workers <= 0:
            raise ConnectorValidationError("max_workers must be positive.")
        self.max_workers = max_workers
        self.requested_team_list: list[str] = teams or []
        self.include_attachments = include_attachments
        self.include_inline_images = include_inline_images
        self.include_meeting_transcripts = include_meeting_transcripts
        self.meeting_organizers: list[str] = (
            meeting_organizers or transcript_organizers or []
        )
        self.include_meeting_chats = include_meeting_chats
        # Channels walked again from their first page in this attempt: a saved
        # page url Graph rejects recovers once per attempt and can never loop.
        self._restarted_channel_ids: set[str] = set()
        self._threads = ThreadSource(self, include_inline_images)
        self._export = ExportSource(self, self._threads)
        self._files: FileSource | None = (
            FileSource(self, self.requested_team_list, lambda: self.raw_file_callback)
            if include_attachments
            else None
        )
        organizer_sources: list[OrganizerSource] = []
        if include_meeting_transcripts:
            organizer_sources.append(
                TranscriptSource(self, covers_every_user=not self.meeting_organizers)
            )
        if include_meeting_chats:
            organizer_sources.append(ChatSource(self, include_inline_images))
        self._organizers: OrganizerStage | None = (
            OrganizerStage(self, self.meeting_organizers, organizer_sources)
            if organizer_sources
            else None
        )
        # The permission sync turns this off once every indexed thread names its
        # group: the group a thread names never changes, so it is not read again.
        self._perm_sync_lists_threads = True
        # The group sync lists members and sites over the same channels.
        self._group_sync_channel_refs: list[ChannelRef] | None = None

    # impls for BaseConnector

    def set_allow_images(self, value: bool) -> None:
        self.allow_images = value

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.open(credentials)
        return None

    def validate_connector_settings(self) -> None:
        if self.graph_client is None:
            raise ConnectorMissingCredentialError("Teams credentials not loaded.")

        # Check if any requested teams have special characters that need client-side filtering
        has_special_chars = listing.has_odata_incompatible_chars(
            self.requested_team_list
        )
        if has_special_chars:
            logger.info(
                "Some requested team names contain special characters (&, (, )) that require "
                "client-side filtering during data retrieval."
            )

        # Minimal validation: just check if we can access the teams endpoint
        timeout = 10  # Short timeout for basic validation

        try:
            # For validation, do a lightweight check instead of full team search
            logger.info(
                "Requested team count: %s, Has special chars: %s",
                len(self.requested_team_list) if self.requested_team_list else 0,
                has_special_chars,
            )

            # The attachments probe picks a channel from this listing.
            validation_query = self.graph_client.teams.get().top(
                50 if self.include_attachments else 1
            )
            run_with_timeout(
                timeout=timeout,
                func=lambda: validation_query.execute_query(),
            )

            logger.info(
                "Teams validation successful - Access to teams endpoint confirmed"
            )

        except TimeoutError as e:
            raise ConnectorValidationError(
                f"Timeout while validating Teams access (waited {timeout}s). "
                f"This may indicate network issues or authentication problems. "
                f"Error: {e}"
            )

        except ClientRequestException as e:
            if not e.response:
                raise RuntimeError(f"No response provided in error; {e=}")
            status_code = e.response.status_code
            if status_code == 401:
                raise CredentialExpiredError(
                    "Invalid or expired Microsoft Teams credentials (401 Unauthorized)."
                )
            elif status_code == 403:
                raise InsufficientPermissionsError(
                    "Your app lacks sufficient permissions to read Teams (403 Forbidden)."
                )
            raise UnexpectedValidationError(f"Unexpected error retrieving teams: {e}")

        except Exception as e:
            error_str = str(e).lower()
            if (
                "unauthorized" in error_str
                or "401" in error_str
                or "invalid_grant" in error_str
            ):
                raise CredentialExpiredError(
                    "Invalid or expired Microsoft Teams credentials."
                )
            elif "forbidden" in error_str or "403" in error_str:
                raise InsufficientPermissionsError(
                    "App lacks required permissions to read from Microsoft Teams."
                )
            raise ConnectorValidationError(
                f"Unexpected error during Teams validation: {e}"
            )

        if self._files is not None:
            self._files.validate(list(validation_query))
        if self._organizers is not None:
            self._organizers.validate()

    # impls for CheckpointedConnector

    def build_dummy_checkpoint(self) -> TeamsCheckpoint:
        return TeamsCheckpoint(
            has_more=True,
        )

    def validate_checkpoint_json(self, checkpoint_json: str) -> TeamsCheckpoint:
        return TeamsCheckpoint.model_validate_json(checkpoint_json)

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: TeamsCheckpoint,
    ) -> CheckpointOutput[TeamsCheckpoint]:
        graph_client = self.graph()

        checkpoint = copy.deepcopy(checkpoint)
        if checkpoint.current_channel is not None:
            checkpoint.active.append(
                ChannelCursor(
                    channel=checkpoint.current_channel,
                    next_messages_url=checkpoint.next_messages_url,
                )
            )
            checkpoint.current_channel = None
            checkpoint.next_messages_url = None

        if checkpoint.todo_team_ids is None:
            teams = listing.collect_all_teams(
                graph_client=graph_client,
                requested=self.requested_team_list,
            )
            checkpoint.todo_team_ids = [team.id for team in teams if team.id]
        elif checkpoint.active or checkpoint.todo_channels:
            yield from self._channel_step(checkpoint, start)
        elif checkpoint.todo_team_ids:
            if checkpoint.export is None:
                probe = self._export.available(checkpoint.todo_team_ids[-1])
                # A probe team that is gone or locked says nothing about the
                # app: it walks its channels and the next team probes again.
                if probe is not ExportProbe.REFUSED_FOR_ITEM:
                    checkpoint.export = probe is ExportProbe.ANSWERS
            if checkpoint.export:
                yield from self._export_step(checkpoint, start, end)
            else:
                team_id = checkpoint.todo_team_ids.pop()
                checkpoint.todo_channels = listing.team_channels(graph_client, team_id)
                logger.info(
                    "Listed %s channel(s) of team %s; %s team(s) left",
                    len(checkpoint.todo_channels),
                    team_id,
                    len(checkpoint.todo_team_ids),
                )
        elif self._organizers is not None and checkpoint.todo_organizers:
            yield from self._organizers.index_batch(
                checkpoint.todo_organizers, start, end
            )
        elif self._organizers is not None and (
            checkpoint.todo_organizers is None or checkpoint.next_organizers_url
        ):
            checkpoint.todo_organizers, checkpoint.next_organizers_url = (
                self._organizers.next_page(checkpoint.next_organizers_url)
            )

        checkpoint.has_more = bool(
            checkpoint.active
            or checkpoint.todo_channels
            or checkpoint.todo_team_ids
            or (
                self._organizers is not None
                and (
                    checkpoint.todo_organizers is None
                    or checkpoint.todo_organizers
                    or checkpoint.next_organizers_url
                )
            )
        )
        return checkpoint

    def _export_step(
        self,
        checkpoint: TeamsCheckpoint,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> Iterator[Document | ConnectorFailure]:
        """The threads of a few teams, each team one export stream, side by
        side and yielded as each team finishes, then the files of their
        channels. The teams leave the queue only once every one finished, so
        a raise in one leaves the step to be retried."""
        if checkpoint.todo_team_ids is None:
            raise RuntimeError("The teams are listed before any export step")
        team_ids: list[str] = checkpoint.todo_team_ids[-EXPORT_TEAM_WORKERS:]

        def one_team(team_id: str) -> Iterator[TeamExport]:
            yield self._export.team(team_id, start, end)

        for export in drain(team_ids, one_team, EXPORT_TEAM_WORKERS):
            yield from export.items
            if export.refused_to_app:
                # A 402 applies to the whole tenant, so the teams left walk
                # their channels without another stream each.
                checkpoint.export = False
            if export.fell_back:
                checkpoint.todo_channels.extend(export.channels)
                continue
            for channel in export.channels:
                yield from self._opened_channel_files(channel, start)
        del checkpoint.todo_team_ids[-EXPORT_TEAM_WORKERS:]

    def _opened_channel_files(
        self, channel: ChannelRef, start: SecondsSinceUnixEpoch
    ) -> Iterator[Document | ConnectorFailure]:
        """A channel's files, library opened and left here. A channel Graph
        describes without a library, or refuses, is one recorded failure.
        Anything else fails the attempt."""
        if self._files is None:
            return
        try:
            self._files.open(channel)
        except ChannelFilesUnavailable as e:
            yield channel_failure(channel, "files", e)
            return
        except requests.HTTPError as e:
            if not is_permanent(e):
                raise
            yield channel_failure(channel, "files", e)
            return
        try:
            yield from self._channel_files(channel, start)
        finally:
            self._files.leave(channel)

    def _channel_step(
        self, checkpoint: TeamsCheckpoint, start: SecondsSinceUnixEpoch
    ) -> Iterator[Document | ConnectorFailure]:
        """One page of every active channel, side by side, then the files of
        each channel whose last page this was. Cursors are advanced on copies
        and written back only once every channel finished its page, so a raise
        in one leaves the whole step to be retried."""
        while len(checkpoint.active) < self.max_workers and checkpoint.todo_channels:
            checkpoint.active.append(
                ChannelCursor(channel=checkpoint.todo_channels.pop())
            )
        # One transient failure discards the other channels' finished pages,
        # up to max_workers - 1 pages of replies calls: cheaper than a partial
        # write-back the retry would have to reconcile.
        advances: list[ChannelAdvance] = cast(
            list[ChannelAdvance],
            run_functions_tuples_in_parallel(
                [
                    (self._advance_channel, (cursor.model_copy(deep=True), start))
                    for cursor in checkpoint.active
                ],
                max_workers=self.max_workers,
            ),
        )
        active: list[ChannelCursor] = []
        for advance in advances:
            yield from advance.items
            if advance.restarted:
                self._restarted_channel_ids.add(advance.cursor.channel.id)
            if not advance.done:
                active.append(advance.cursor)
                continue
            # The SharePoint REST client behind file readers is not safe across
            # threads, so a channel's files are read here, after its last page.
            if advance.files_due and self._files is not None:
                yield from self._channel_files(advance.cursor.channel, start)
            if self._files is not None:
                self._files.leave(advance.cursor.channel)
        checkpoint.active = active

    def _advance_channel(
        self, cursor: ChannelCursor, start: SecondsSinceUnixEpoch
    ) -> ChannelAdvance:
        """One page of the cursor's channel: its threads with their replies and
        images. Done when the page was its last or is refused; the step leaves
        the channel."""
        channel = cursor.channel
        items: list[Document | ConnectorFailure] = []

        type_failure = self._threads.type_failure(channel)
        if type_failure is not None:
            items.append(type_failure)
            return ChannelAdvance(cursor=cursor, items=items, done=True)

        # No library means the files grant the admin turned on is missing, so a
        # refusal is one channel failure.
        try:
            if self._files is not None:
                try:
                    self._files.open(channel)
                except ChannelFilesUnavailable as e:
                    # Graph describes no usable library for this channel. Its
                    # messages are still readable, so only the files are lost.
                    items.append(channel_failure(channel, "files", e))
        except requests.HTTPError as e:
            if not is_permanent(e):
                raise
            items.append(channel_failure(channel, "files", e))
            return ChannelAdvance(cursor=cursor, items=items, done=True)

        try:
            roots, next_url = self._threads.page(
                channel, cursor.next_messages_url, start
            )
        except requests.HTTPError as e:
            if _rejects_saved_cursor(e, cursor, self._restarted_channel_ids):
                logger.warning(
                    "Graph rejected the saved page of channel %s; walking it again "
                    "from its first page",
                    channel.id,
                )
                cursor.next_messages_url = None
                return ChannelAdvance(cursor=cursor, items=items, restarted=True)
            if not is_permanent(e):
                raise
            items.append(channel_failure(channel, "messages", e))
            return ChannelAdvance(cursor=cursor, items=items, done=True)

        items.extend(self._threads.documents(channel, roots, start))
        cursor.next_messages_url = next_url
        return ChannelAdvance(
            cursor=cursor,
            items=items,
            done=next_url is None,
            files_due=next_url is None,
        )

    def _channel_files(
        self, channel: ChannelRef, start: SecondsSinceUnixEpoch
    ) -> Iterator[Document | ConnectorFailure]:
        """The files follow the last page of messages. A refused folder listing
        on Graph or a refused site on SharePoint REST (the SDK's own exception)
        is one recorded failure for the channel, anything else fails the attempt."""
        if self._files is None:
            raise RuntimeError("Channel files are read only when attachments are on")
        try:
            yield from self._files.index(channel, start)
        except (requests.HTTPError, ClientRequestException) as e:
            if not is_permanent(e):
                raise
            yield channel_failure(channel, "files", e)

    def _channels(self, for_group_sync: bool = False) -> Iterator[ChannelRef]:
        """Every channel of the configured teams, listed fresh. The group sync
        leaves out a team whose channel listing is refused, where the slim walk
        raises: a channel missing from that walk would have its documents pruned."""
        list_channels = (
            groups.group_sync_channels
            if for_group_sync
            else listing.collect_all_channels_from_team
        )
        teams = listing.collect_all_teams(
            graph_client=self.graph(), requested=self.requested_team_list
        )
        for team in teams:
            if not team.id:
                logger.warning(
                    "Expected a team with an id, instead got no id: team=%r", team
                )
                continue
            for channel in list_channels(team=team):
                if not channel.id:
                    logger.warning(
                        "Expected a channel with an id, instead got no id: channel=%r",
                        channel,
                    )
                    continue
                yield listing.channel_ref(team.id, channel)

    def channel_site_urls(self) -> Iterator[str]:
        """The distinct SharePoint sites behind the configured teams' channels,
        for the group sync."""
        if self._files is None:
            return iter(())
        return self._files.site_urls(self._group_sync_channels())

    def channel_member_groups(self) -> Iterator[tuple[str, list[str]]]:
        """Each group a thread names and the emails in it, for the group sync."""
        return groups.channel_member_groups(self, self._group_sync_channels())

    def _group_sync_channels(self) -> Iterator[ChannelRef]:
        """Listed once per run. The first listing streams, so the groups ahead of
        a failure are still synced, and the second replays a finished one. A
        first listing that stopped early is not kept, so the next call lists
        again rather than replay a part."""
        if self._group_sync_channel_refs is not None:
            yield from self._group_sync_channel_refs
            return
        refs: list[ChannelRef] = []
        for channel in self._channels(for_group_sync=True):
            refs.append(channel)
            yield channel
        self._group_sync_channel_refs = refs

    def rest_context(self, site_url: str) -> ClientContext:
        if self._files is None:
            raise RuntimeError("Channel files are not part of this connector")
        return self._files.rest_context(site_url)

    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: TeamsCheckpoint,
    ) -> CheckpointOutput[TeamsCheckpoint]:
        # Every document already carries its readers, so the plain walk is the
        # permission walk.
        return self.load_from_checkpoint(start, end, checkpoint)

    # impls for SlimConnectorWithPermSync

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """Ids alone, for pruning. Readers cost calls to Graph and SharePoint
        that pruning would throw away."""
        yield from self._slim_docs(start, callback, with_readers=False)

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        yield from self._slim_docs(
            start,
            callback,
            with_readers=True,
            lists_threads=self._perm_sync_lists_threads,
        )

    def skip_threads_in_perm_sync(self) -> None:
        """For the permission sync, once every indexed thread names its group.
        The sync then leaves threads out of the walk and out of the step that
        empties the access of what a walk did not list."""
        self._perm_sync_lists_threads = False

    def _slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None,
        callback: IndexingHeartbeatInterface | None,
        with_readers: bool,
        lists_threads: bool = True,
    ) -> GenerateSlimDocumentOutput:
        walk = SlimWalk(
            start=start or 0,
            callback=callback,
            with_readers=with_readers,
            lists_threads=lists_threads,
        )
        yield from batch_generator(
            chain(self._slim_channels(walk), self._slim_organizers(walk)),
            _SLIM_DOC_BATCH_SIZE,
            pre_batch_yield=lambda _: walk.batch_signals(),
        )

    def _slim_channels(self, walk: SlimWalk) -> Iterator[SlimDocument]:
        """Every channel's documents. With no thread and no file to list, no
        team or channel is listed either."""
        if not walk.lists_threads and self._files is None:
            return
        yield from walk.fan_out(
            self._channels(),
            lambda channel: self._slim_channel(channel, walk),
            self.max_workers,
            self.max_workers * CHANNEL_BATCH_PER_WORKER,
        )

    def _slim_organizers(self, walk: SlimWalk) -> Iterator[SlimDocument]:
        if self._organizers is not None:
            yield from self._organizers.slim(walk)

    def _slim_channel(
        self, channel: ChannelRef, walk: SlimWalk
    ) -> Iterator[SlimDocument]:
        if walk.lists_threads:
            yield from self._threads.slim(channel, walk)
        if self._files is not None:
            yield from self._files.slim(channel, walk)


def _rejects_saved_cursor(
    error: requests.HTTPError,
    cursor: ChannelCursor,
    restarted_channel_ids: set[str],
) -> bool:
    """Graph answers a page url it no longer honors with 400 or 410 (measured
    for a tampered skip token). Retrying it would never progress, so the channel
    is walked again from its first page, once per attempt."""
    return (
        cursor.next_messages_url is not None
        and cursor.channel.id not in restarted_channel_ids
        and status(error) in (400, 410)
    )


if __name__ == "__main__":
    from tests.daily.connectors.utils import load_all_from_connector

    app_id = os.environ["TEAMS_APPLICATION_ID"]
    dir_id = os.environ["TEAMS_DIRECTORY_ID"]
    secret = os.environ["TEAMS_SECRET"]

    teams_env_var = os.environ.get("TEAMS", None)
    teams = teams_env_var.split(",") if teams_env_var else []

    teams_connector = TeamsConnector(teams=teams)
    teams_connector.load_credentials(
        {
            "teams_client_id": app_id,
            "teams_directory_id": dir_id,
            "teams_client_secret": secret,
        }
    )
    teams_connector.validate_connector_settings()

    for _slim_doc in teams_connector.retrieve_all_slim_docs_perm_sync():
        ...

    for doc in load_all_from_connector(
        connector=teams_connector,
        start=0.0,
        end=datetime.now(tz=timezone.utc).timestamp(),
    ).documents:
        print(doc)
