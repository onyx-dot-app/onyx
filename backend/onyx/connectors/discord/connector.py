import asyncio
from collections.abc import Awaitable
from collections.abc import Callable
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast
from typing import TypeVar

from discord import Client
from discord import Object as DiscordObject
from discord.abc import Messageable
from discord.channel import ForumChannel
from discord.channel import TextChannel
from discord.channel import Thread
from discord.enums import MessageType
from discord.errors import Forbidden
from discord.errors import HTTPException
from discord.errors import LoginFailure
from discord.errors import NotFound
from discord.errors import RateLimited
from discord.flags import Intents
from discord.message import Message as DiscordMessage
from typing_extensions import override

from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    datetime_from_utc_timestamp,
)
from onyx.connectors.discord.models import DiscordCheckpoint
from onyx.connectors.exceptions import CredentialInvalidError
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import EntityFailure
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_async_sync_no_cancel

logger = setup_logger()


_DISCORD_DOC_ID_PREFIX = "DISCORD_"
_SNIPPET_LENGTH = 30
_PAGE_SIZE = 100
_ARCHIVED_THREADS_PAGE_SIZE = 100
# Sentinel value for `archived_thread_cursor`: "first archived page, no
# before= snowflake yet". Empty string is unambiguous because real cursors
# are stringified ints from snowflake IDs.
_ARCHIVED_CURSOR_BEGIN = ""

# Permanent per-channel/thread failures: skip and yield ConnectorFailure.
# Transient failures (HTTPException 5xx, RateLimited) are retried inside the
# helpers via _retry_transient; if they bubble out of that retry budget they
# propagate up so the framework retries the attempt from the persisted
# checkpoint.
_HISTORY_FAILURE_ERRORS: tuple[type[Exception], ...] = (
    Forbidden,
    NotFound,
)

_TRANSIENT_RETRY_ATTEMPTS = 3
_TRANSIENT_RETRY_BASE_SECONDS = 1.0
_TRANSIENT_RETRY_MAX_BACKOFF_SECONDS = 30.0

T = TypeVar("T")


async def _retry_transient(
    op_label: str,
    coro_factory: Callable[[], Awaitable[T]],
) -> T:
    """Retry transient discord.py errors with exponential backoff before giving
    up. Permanent errors (Forbidden, NotFound) are not caught here; callers
    handle those as ConnectorFailure. After exhausting attempts on transient
    errors the last exception propagates so the framework retries the attempt
    from the persisted checkpoint."""
    last_exc: Exception | None = None
    total_backoff = 0.0
    for attempt in range(_TRANSIENT_RETRY_ATTEMPTS):
        try:
            return await coro_factory()
        except RateLimited as e:
            last_exc = e
            wait_s = min(
                float(getattr(e, "retry_after", 0.0))
                or _TRANSIENT_RETRY_BASE_SECONDS * (2**attempt),
                _TRANSIENT_RETRY_MAX_BACKOFF_SECONDS - total_backoff,
            )
        except HTTPException as e:
            # 4xx other than the permanent ones we let bubble (Forbidden,
            # NotFound) is permanent for this entity; do not retry.
            if e.status < 500:
                raise
            last_exc = e
            wait_s = min(
                _TRANSIENT_RETRY_BASE_SECONDS * (2**attempt),
                _TRANSIENT_RETRY_MAX_BACKOFF_SECONDS - total_backoff,
            )
        if wait_s <= 0 or attempt == _TRANSIENT_RETRY_ATTEMPTS - 1:
            break
        logger.warning(
            f"Discord {op_label} transient failure (attempt {attempt + 1}); "
            f"sleeping {wait_s:.1f}s before retry: {last_exc}"
        )
        await asyncio.sleep(wait_s)
        total_backoff += wait_s
    assert last_exc is not None
    raise last_exc


def _message_to_document(message: DiscordMessage) -> Document:
    metadata: dict[str, str | list[str]] = {}
    semantic_substring = ""

    if isinstance(message.channel, TextChannel):
        channel_name = message.channel.name
        if channel_name:
            metadata["Channel"] = channel_name
            semantic_substring += f" in Channel: #{channel_name}"

    title = ""
    if isinstance(message.channel, Thread):
        title = message.channel.name
        metadata["Thread"] = title
        semantic_substring += f" in Thread: {title}"

    snippet = (
        message.content[:_SNIPPET_LENGTH].rstrip() + "..."
        if len(message.content) > _SNIPPET_LENGTH
        else message.content
    )
    semantic_identifier = f"{message.author.name} said{semantic_substring}: {snippet}"

    sections: list[TextSection] = [
        TextSection(text=message.content, link=message.jump_url)
    ]
    return Document(
        id=f"{_DISCORD_DOC_ID_PREFIX}{message.id}",
        source=DocumentSource.DISCORD,
        semantic_identifier=semantic_identifier,
        doc_updated_at=message.edited_at,
        title=title,
        sections=cast(list[TextSection | ImageSection], sections),
        metadata=metadata,
    )


def _parse_start_date(start_date: str) -> datetime | None:
    if not start_date:
        return None
    return datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _resolve_window(
    pull_date: datetime | None,
    start: SecondsSinceUnixEpoch,
    end: SecondsSinceUnixEpoch,
) -> tuple[datetime | None, datetime]:
    requested_start = datetime_from_utc_timestamp(int(start)) if start else None
    end_dt = datetime_from_utc_timestamp(int(end))
    candidates = [d for d in (requested_start, pull_date) if d is not None]
    return (max(candidates) if candidates else None, end_dt)


def _build_client() -> Client:
    intents = Intents.default()
    intents.message_content = True
    return Client(intents=intents)


# ---------- Async helpers (single-page granularity) ----------


async def _list_channel_ids(
    token: str,
    server_ids: set[int],
    channel_names: set[str],
    include_forum_channels: bool,
) -> tuple[list[str], set[str]]:
    """Returns (channel_ids, forum_channel_ids). The latter is the subset of the
    former whose Discord channel type is ForumChannel; consumers use it to skip
    phase 2 (forums have no main-channel history)."""
    # REST-only: gateway-cached `get_all_channels()` and `guild.me` are unavailable.
    client = _build_client()
    try:
        await client.login(token)
        bot_user = client.user
        if bot_user is None:
            raise CredentialInvalidError("Discord login did not populate client.user")

        allowed: tuple[type, ...] = (
            (TextChannel, ForumChannel) if include_forum_channels else (TextChannel,)
        )

        result: list[str] = []
        forum_ids: set[str] = set()
        async for partial_guild in client.fetch_guilds(limit=None):
            if server_ids and partial_guild.id not in server_ids:
                continue
            # Partial guilds from fetch_guilds() have no role cache, so Member.roles
            # returns Nones and channel.permissions_for(member) silently misclassifies.
            # Re-fetch as a full Guild so role overwrites resolve correctly.
            try:
                guild = await client.fetch_guild(partial_guild.id)
                bot_member = await guild.fetch_member(bot_user.id)
                channels = await guild.fetch_channels()
            except (Forbidden, NotFound, HTTPException):
                logger.warning(f"Skipping guild {partial_guild.id}: REST access denied")
                continue

            for channel in channels:
                if not isinstance(channel, allowed):
                    continue
                if channel_names and channel.name not in channel_names:
                    continue
                if not channel.permissions_for(bot_member).read_message_history:
                    continue
                result.append(str(channel.id))
                if isinstance(channel, ForumChannel):
                    forum_ids.add(str(channel.id))
        return result, forum_ids
    finally:
        await client.close()


async def _fetch_history_page(
    token: str,
    channel_id: int,
    before_snowflake: int | None,
    after: datetime | None,
    before_time: datetime,
) -> tuple[list[Document], list[ConnectorFailure], str | None, int]:
    # `before_snowflake` (when set) takes precedence: resume cursors must be exact.
    client = _build_client()
    try:
        await client.login(token)
        messageable = cast(Messageable, await client.fetch_channel(channel_id))
        before_arg: DiscordObject | datetime = (
            DiscordObject(id=before_snowflake) if before_snowflake else before_time
        )

        async def _iterate_page() -> tuple[
            list[Document], list[ConnectorFailure], str | None, int
        ]:
            documents: list[Document] = []
            failures: list[ConnectorFailure] = []
            oldest_seen: int | None = None
            raw_count = 0
            # `oldest_first=False` is required: cursor logic (`before=` + min snowflake)
            # assumes newest-first iteration. discord.py defaults to oldest-first when
            # `after` is set, which silently breaks pagination resume.
            async for message in messageable.history(
                limit=_PAGE_SIZE, before=before_arg, after=after, oldest_first=False
            ):
                raw_count += 1
                oldest_seen = (
                    message.id if oldest_seen is None else min(oldest_seen, message.id)
                )
                if message.type != MessageType.default:
                    continue
                try:
                    documents.append(_message_to_document(message))
                except Exception as e:
                    failures.append(
                        ConnectorFailure(
                            failed_document=DocumentFailure(
                                document_id=f"{_DISCORD_DOC_ID_PREFIX}{message.id}",
                                document_link=message.jump_url,
                            ),
                            failure_message=f"Failed to convert Discord message: {e}",
                            exception=e,
                        )
                    )
            return (
                documents,
                failures,
                str(oldest_seen) if oldest_seen else None,
                raw_count,
            )

        return await _retry_transient(
            f"history page channel={channel_id}", _iterate_page
        )
    finally:
        await client.close()


async def _enumerate_active_threads(token: str, channel_id: int) -> list[str]:
    """Return active threads parented at `channel_id`. Active-thread enumeration
    is a single REST call (no pagination) so this runs in one cycle."""
    # `channel.threads` is gateway-only (always empty here); use REST endpoints.
    client = _build_client()
    try:
        await client.login(token)
        channel = await client.fetch_channel(channel_id)
        if not isinstance(channel, (TextChannel, ForumChannel)):
            return []

        async def _fetch_active() -> list[str]:
            thread_ids: list[str] = []
            active_threads = await channel.guild.active_threads()
            for thread in active_threads:
                if thread.parent_id == channel.id:
                    thread_ids.append(str(thread.id))
            return thread_ids

        return await _retry_transient(
            f"active threads channel={channel_id}", _fetch_active
        )
    finally:
        await client.close()


async def _fetch_archived_threads_page(
    token: str,
    channel_id: int,
    before_snowflake: int | None,
) -> tuple[list[str], str | None]:
    """Fetch one page (up to `_ARCHIVED_THREADS_PAGE_SIZE`) of archived threads
    for `channel_id`. Returns `(thread_ids, next_cursor)` where `next_cursor` is
    the oldest archived-thread snowflake on the page; callers pass it as
    `before_snowflake` to fetch the next page. A page with fewer than
    `_ARCHIVED_THREADS_PAGE_SIZE` results indicates archived enumeration is
    complete.

    The `archived_threads(limit=N, before=Snowflake)` shape is identical on
    both TextChannel and ForumChannel."""
    client = _build_client()
    try:
        await client.login(token)
        channel = await client.fetch_channel(channel_id)
        if not isinstance(channel, (TextChannel, ForumChannel)):
            return [], None

        async def _fetch_page() -> tuple[list[str], str | None]:
            before_arg = (
                DiscordObject(id=before_snowflake) if before_snowflake else None
            )
            thread_ids: list[str] = []
            oldest_seen: int | None = None
            async for archived in channel.archived_threads(
                limit=_ARCHIVED_THREADS_PAGE_SIZE, before=before_arg
            ):
                thread_ids.append(str(archived.id))
                oldest_seen = (
                    archived.id
                    if oldest_seen is None
                    else min(oldest_seen, archived.id)
                )
            return thread_ids, str(oldest_seen) if oldest_seen is not None else None

        return await _retry_transient(
            f"archived threads channel={channel_id}", _fetch_page
        )
    finally:
        await client.close()


# ---------- Connector class ----------


class DiscordConnector(CheckpointedConnector[DiscordCheckpoint]):
    def __init__(
        self,
        server_ids: list[str] | None = None,
        channel_names: list[str] | None = None,
        # YYYY-MM-DD
        start_date: str | None = None,
        # Defaults preserve PR1 behavior for connector specs that predate PR2:
        # forums were never indexed (False); archived threads were always drained (True).
        include_forum_channels: bool = False,
        include_archived_threads: bool = True,
    ) -> None:
        self.channel_names: set[str] = set(channel_names) if channel_names else set()
        self.server_ids: set[int] = (
            {int(server_id) for server_id in server_ids} if server_ids else set()
        )
        self._discord_bot_token: str | None = None
        self.requested_start_date_string: str = start_date or ""
        self.include_forum_channels = include_forum_channels
        self.include_archived_threads = include_archived_threads

    @property
    def discord_bot_token(self) -> str:
        if self._discord_bot_token is None:
            raise ConnectorMissingCredentialError("Discord")
        return self._discord_bot_token

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._discord_bot_token = credentials["discord_bot_token"]
        return None

    @override
    def validate_connector_settings(self) -> None:
        async def _login_only() -> None:
            client = _build_client()
            try:
                await client.login(self.discord_bot_token)
            finally:
                await client.close()

        try:
            run_async_sync_no_cancel(_login_only())
        except LoginFailure as e:
            raise CredentialInvalidError(f"Invalid Discord bot token: {e}")

    @override
    def build_dummy_checkpoint(self) -> DiscordCheckpoint:
        return DiscordCheckpoint(
            channel_ids=None,
            forum_channel_ids=[],
            channel_completion_map={},
            current_channel_id=None,
            current_channel_main_exhausted=False,
            current_channel_thread_ids=None,
            archived_thread_cursor=None,
            thread_completion_map={},
            current_thread_id=None,
            has_more=True,
        )

    @override
    def validate_checkpoint_json(self, checkpoint_json: str) -> DiscordCheckpoint:
        return DiscordCheckpoint.model_validate_json(checkpoint_json)

    # ---- State machine: one transition per load_from_checkpoint call ----

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: DiscordCheckpoint,
    ) -> CheckpointOutput[DiscordCheckpoint]:
        """Five-phase state machine; one transition per call.

        1. Cold start          - enumerate channels.
        2. Main-channel page   - fetch one history page (yields docs).
        3a. Active-thread enum - one-shot, initializes thread queue + archived cursor.
        3b. Archived-thread enum - one archived-threads page per cycle (bounded).
        4. Thread page         - fetch one thread history page (yields docs).
        5. Channel rollover    - advance to next channel or finish.
        """
        checkpoint = checkpoint.model_copy()
        after, before_time = _resolve_window(
            _parse_start_date(self.requested_start_date_string), start, end
        )

        if checkpoint.channel_ids is None:
            return self._phase_cold_start(checkpoint)

        if checkpoint.current_channel_id is None:
            checkpoint.has_more = False
            return checkpoint

        if not checkpoint.current_channel_main_exhausted:
            return (
                yield from self._fetch_page(
                    checkpoint, after, before_time, is_thread=False
                )
            )

        # Phase 3a: thread queue not initialized yet.
        if checkpoint.current_channel_thread_ids is None:
            return (yield from self._phase_thread_enum(checkpoint, after, before_time))

        # Phase 3b: thread queue initialized but archived enumeration in progress.
        # Drain one archived page per cycle to stay within the heartbeat budget.
        if checkpoint.archived_thread_cursor is not None:
            return (yield from self._phase_thread_enum(checkpoint, after, before_time))

        if checkpoint.current_thread_id is not None:
            return (
                yield from self._fetch_page(
                    checkpoint, after, before_time, is_thread=True
                )
            )

        return self._phase_rollover(checkpoint)

    def _phase_cold_start(self, checkpoint: DiscordCheckpoint) -> DiscordCheckpoint:
        try:
            channel_ids, forum_ids = run_async_sync_no_cancel(
                _list_channel_ids(
                    self.discord_bot_token,
                    self.server_ids,
                    self.channel_names,
                    self.include_forum_channels,
                )
            )
        except LoginFailure as e:
            raise CredentialInvalidError(f"Invalid Discord bot token: {e}")
        logger.info(
            f"Discord channel discovery: found {len(channel_ids)} channels "
            f"({len(forum_ids)} forum)"
        )
        checkpoint.channel_ids = channel_ids
        checkpoint.forum_channel_ids = sorted(forum_ids)
        first = channel_ids[0] if channel_ids else None
        checkpoint.current_channel_id = first
        # Forums have no main-channel history; pre-skip phase 2 so the dispatcher
        # routes straight to thread enumeration.
        checkpoint.current_channel_main_exhausted = (
            first is not None and first in forum_ids
        )
        checkpoint.has_more = first is not None
        return checkpoint

    def _phase_thread_enum(
        self,
        checkpoint: DiscordCheckpoint,
        after: datetime | None,
        before_time: datetime,
    ) -> CheckpointOutput[DiscordCheckpoint]:
        """Phase 3 — thread enumeration, paginated across cycles.

        Two sub-phases share this method, dispatched on the checkpoint shape:

        - Phase 3a (`current_channel_thread_ids is None`): single REST call to
          fetch active threads for the current channel. Initializes the thread
          queue (possibly empty) and primes `archived_thread_cursor` to
          `_ARCHIVED_CURSOR_BEGIN` so the next cycle starts archived pagination.
        - Phase 3b (`current_channel_thread_ids is not None` and
          `archived_thread_cursor is not None`): one archived-threads page per
          cycle. When the page is full we save the oldest snowflake as the
          cursor and return; the next cycle picks up from there. When the page
          is partial we mark archived enumeration complete by setting
          `archived_thread_cursor = None` and seeding `current_thread_id` so
          phase 4 can take over.
        """
        assert checkpoint.current_channel_id is not None
        channel_id = checkpoint.current_channel_id

        # Phase 3a: enumerate active threads, initialize archived cursor.
        if checkpoint.current_channel_thread_ids is None:
            try:
                thread_ids = run_async_sync_no_cancel(
                    _enumerate_active_threads(
                        self.discord_bot_token, int(channel_id)
                    )
                )
            except _HISTORY_FAILURE_ERRORS as e:
                logger.exception(
                    f"Failed to enumerate active threads for {channel_id}"
                )
                yield _entity_failure(
                    channel_id, after, before_time, "thread enumeration", e
                )
                # Skip both archived enumeration and phase 4 for this channel.
                checkpoint.current_channel_thread_ids = []
                checkpoint.archived_thread_cursor = None
                return checkpoint
            checkpoint.current_channel_thread_ids = thread_ids
            if self.include_archived_threads:
                # Phase 3b will paginate archived threads on the next cycle.
                checkpoint.archived_thread_cursor = _ARCHIVED_CURSOR_BEGIN
            else:
                # Archived enumeration disabled: skip phase 3b and head straight
                # to phase 4 with the active threads we have.
                checkpoint.archived_thread_cursor = None
                checkpoint.current_thread_id = thread_ids[0] if thread_ids else None
            return checkpoint

        # Phase 3b: fetch one archived-threads page.
        assert checkpoint.archived_thread_cursor is not None
        before_snowflake = (
            int(checkpoint.archived_thread_cursor)
            if checkpoint.archived_thread_cursor != _ARCHIVED_CURSOR_BEGIN
            else None
        )
        try:
            archived_ids, next_cursor = run_async_sync_no_cancel(
                _fetch_archived_threads_page(
                    self.discord_bot_token, int(channel_id), before_snowflake
                )
            )
        except _HISTORY_FAILURE_ERRORS as e:
            logger.exception(
                f"Failed to enumerate archived threads for {channel_id}"
            )
            yield _entity_failure(
                channel_id, after, before_time, "archived thread enumeration", e
            )
            # Stop archived enumeration and let any already-collected active +
            # archived threads drain via phase 4 normally.
            checkpoint.archived_thread_cursor = None
            checkpoint.current_thread_id = (
                checkpoint.current_channel_thread_ids[0]
                if checkpoint.current_channel_thread_ids
                else None
            )
            return checkpoint

        # Append-not-reassign keeps this consistent with the shallow-copy
        # discipline used elsewhere (the model_copy at dispatch already gave
        # us our own list reference).
        new_thread_ids = list(checkpoint.current_channel_thread_ids) + archived_ids
        checkpoint.current_channel_thread_ids = new_thread_ids

        if len(archived_ids) < _ARCHIVED_THREADS_PAGE_SIZE:
            # Partial page -> archived enumeration complete; transition to phase 4.
            checkpoint.archived_thread_cursor = None
            checkpoint.current_thread_id = new_thread_ids[0] if new_thread_ids else None
        else:
            # Full page -> more archived threads remain; advance the cursor.
            checkpoint.archived_thread_cursor = next_cursor
        return checkpoint

    def _phase_rollover(self, checkpoint: DiscordCheckpoint) -> DiscordCheckpoint:
        # Advance positionally: zero-message channels never appear in
        # channel_completion_map, so a "next not in map" search would loop.
        assert checkpoint.channel_ids is not None
        next_channel: str | None = None
        if checkpoint.current_channel_id is not None:
            assert checkpoint.current_channel_id in checkpoint.channel_ids
            idx = checkpoint.channel_ids.index(checkpoint.current_channel_id)
            next_channel = (
                checkpoint.channel_ids[idx + 1]
                if idx + 1 < len(checkpoint.channel_ids)
                else None
            )
            # Cursor for the channel we're leaving is no longer needed: the
            # channel is either fully drained or skip-failed. Reassign the map
            # wholesale so the shallow copy at dispatch isolates intermediate
            # checkpoints.
            checkpoint.channel_completion_map = {
                channel_id: snowflake
                for channel_id, snowflake in checkpoint.channel_completion_map.items()
                if channel_id != checkpoint.current_channel_id
            }
        checkpoint.current_channel_id = next_channel
        # Forums have no main-channel history; pre-skip phase 2 on rollover into one.
        checkpoint.current_channel_main_exhausted = (
            next_channel is not None and next_channel in checkpoint.forum_channel_ids
        )
        checkpoint.current_channel_thread_ids = None
        checkpoint.archived_thread_cursor = None
        checkpoint.current_thread_id = None
        checkpoint.has_more = next_channel is not None
        return checkpoint

    def _fetch_page(
        self,
        checkpoint: DiscordCheckpoint,
        after: datetime | None,
        before_time: datetime,
        is_thread: bool,
    ) -> CheckpointOutput[DiscordCheckpoint]:
        """Shared body of phases 2 and 4. Differs only in cursor map and the
        on-failure fallthrough."""
        # Reassign the cursor map wholesale so the shallow copy at dispatch
        # isolates intermediate checkpoints from later in-place mutations.
        if is_thread:
            assert checkpoint.current_thread_id is not None
            assert checkpoint.current_channel_thread_ids is not None
            entity_id = checkpoint.current_thread_id
            cursor_map = dict(checkpoint.thread_completion_map)
            checkpoint.thread_completion_map = cursor_map
            sibling_ids = checkpoint.current_channel_thread_ids
            label = "thread history"
        else:
            assert checkpoint.current_channel_id is not None
            entity_id = checkpoint.current_channel_id
            cursor_map = dict(checkpoint.channel_completion_map)
            checkpoint.channel_completion_map = cursor_map
            sibling_ids = []  # unused on the main-channel path
            label = "channel history"

        before_snowflake = (
            int(cursor_map[entity_id]) if entity_id in cursor_map else None
        )
        try:
            documents, failures, oldest, raw_count = run_async_sync_no_cancel(
                _fetch_history_page(
                    self.discord_bot_token,
                    int(entity_id),
                    before_snowflake,
                    after,
                    before_time,
                )
            )
        except _HISTORY_FAILURE_ERRORS as e:
            logger.exception(f"Failed to fetch {label} for {entity_id}")
            yield _entity_failure(entity_id, after, before_time, label, e)
            if is_thread:
                # Drop the cursor for the thread we're abandoning: bounded growth.
                cursor_map.pop(entity_id, None)
                checkpoint.current_thread_id = _next_after(sibling_ids, entity_id)
            else:
                # Main inaccessible -> threads almost certainly are too.
                checkpoint.current_channel_main_exhausted = True
                checkpoint.current_channel_thread_ids = []
                checkpoint.archived_thread_cursor = None
            return checkpoint

        for failure in failures:
            yield failure
        for doc in documents:
            yield doc

        if oldest is not None:
            cursor_map[entity_id] = oldest
        # Use raw_count (not len(documents) + len(failures)): non-default messages
        # are filtered before doc/failure construction, so a page can be full of
        # raw messages while producing fewer entries.
        if raw_count < _PAGE_SIZE:
            if is_thread:
                # Drop the cursor for the exhausted thread: bounded growth.
                cursor_map.pop(entity_id, None)
                checkpoint.current_thread_id = _next_after(sibling_ids, entity_id)
            else:
                checkpoint.current_channel_main_exhausted = True
        return checkpoint


def _entity_failure(
    entity_id: str,
    after: datetime | None,
    before_time: datetime,
    operation: str,
    exception: Exception,
) -> ConnectorFailure:
    return ConnectorFailure(
        failed_entity=EntityFailure(
            entity_id=entity_id,
            missed_time_range=(after, before_time) if after else None,
        ),
        failure_message=f"Discord {operation} failed: {exception}",
        exception=exception,
    )


def _next_after(ids: list[str], current: str) -> str | None:
    try:
        idx = ids.index(current)
    except ValueError:
        return None
    return ids[idx + 1] if idx + 1 < len(ids) else None
