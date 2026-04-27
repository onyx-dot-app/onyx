"""External-dependency unit tests for the checkpointed Discord connector.

Tests patch the connector module's four async helpers
(`_list_channel_ids`, `_fetch_history_page`, `_enumerate_active_threads`,
`_fetch_archived_threads_page`) which are the only seam between the state
machine and the Discord SDK.
"""

from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from discord.enums import MessageType
from discord.errors import Forbidden
from discord.errors import HTTPException

from onyx.connectors.discord import connector as connector_module
from onyx.connectors.discord.connector import DiscordConnector
from onyx.connectors.discord.models import DiscordCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from tests.unit.onyx.connectors.utils import (
    load_everything_from_checkpoint_connector_from_checkpoint,
)

_END = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()


# ----- Fakes --------------------------------------------------------------


def _make_message(msg_id: int) -> MagicMock:
    msg = MagicMock()
    msg.id = msg_id
    msg.content = "hello"
    msg.type = MessageType.default
    msg.author.name = "alice"
    msg.jump_url = f"https://discord.com/channels/1/100/{msg_id}"
    msg.edited_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    # spec=[] defeats isinstance(TextChannel|Thread) so the converter
    # takes the simple no-channel-metadata path.
    msg.channel = MagicMock(spec=[])
    return msg


def _make_doc(msg_id: int) -> Document:
    return connector_module._message_to_document(_make_message(msg_id))


def _http_exception(status: int) -> HTTPException:
    response = MagicMock(status=status, reason="boom")
    return HTTPException(response, "rate limited")


def _forbidden() -> Forbidden:
    response = MagicMock(status=403, reason="Forbidden")
    return Forbidden(response, "denied")


def _make_cp(
    *,
    channel_ids: list[str] | None = None,
    channel_completion_map: dict[str, str] | None = None,
    current_channel_id: str | None = "100",
    current_channel_main_exhausted: bool = False,
    current_channel_thread_ids: list[str] | None = None,
    archived_thread_cursor: str | None = None,
    thread_completion_map: dict[str, str] | None = None,
    current_thread_id: str | None = None,
    has_more: bool = True,
) -> DiscordCheckpoint:
    return DiscordCheckpoint(
        channel_ids=channel_ids if channel_ids is not None else ["100"],
        channel_completion_map=channel_completion_map or {},
        current_channel_id=current_channel_id,
        current_channel_main_exhausted=current_channel_main_exhausted,
        current_channel_thread_ids=current_channel_thread_ids,
        archived_thread_cursor=archived_thread_cursor,
        thread_completion_map=thread_completion_map or {},
        current_thread_id=current_thread_id,
        has_more=has_more,
    )


# Empty-page sentinel used to terminate trailing cycles past the assertion of interest.
_EMPTY_PAGE: tuple[list[Document], list[ConnectorFailure], str | None, int] = (
    [],
    [],
    None,
    0,
)


@pytest.fixture
def connector() -> DiscordConnector:
    c = DiscordConnector()
    c.load_credentials({"discord_bot_token": "fake-token"})
    return c


@pytest.fixture
def helpers() -> Generator[dict[str, AsyncMock], None, None]:
    list_mock = AsyncMock()
    fetch_mock = AsyncMock()
    active_mock = AsyncMock()
    archived_mock = AsyncMock()
    # Sensible defaults that allow the state machine to run to completion
    # without explicit per-test setup, so tests only need to override the
    # helpers whose return values they actually care about.
    fetch_mock.return_value = _EMPTY_PAGE
    active_mock.return_value = []
    # (thread_ids, next_cursor) — empty + None signals "archived enumeration done".
    archived_mock.return_value = ([], None)
    list_mock.return_value = []
    with (
        patch.object(connector_module, "_list_channel_ids", list_mock),
        patch.object(connector_module, "_fetch_history_page", fetch_mock),
        patch.object(connector_module, "_enumerate_active_threads", active_mock),
        patch.object(
            connector_module, "_fetch_archived_threads_page", archived_mock
        ),
    ):
        yield {
            "list": list_mock,
            "fetch": fetch_mock,
            "active": active_mock,
            "archived": archived_mock,
        }


# ----- Tests --------------------------------------------------------------


def test_cold_start_enumerates_channels(
    connector: DiscordConnector, helpers: dict[str, AsyncMock]
) -> None:
    helpers["list"].return_value = ["100", "200"]

    outputs = load_everything_from_checkpoint_connector_from_checkpoint(
        connector, 0, _END, connector.build_dummy_checkpoint()
    )

    # First cycle: cold start populates channel_ids and selects the first.
    assert outputs[0].items == []
    cold = outputs[0].next_checkpoint
    assert cold.channel_ids == ["100", "200"]
    assert cold.current_channel_id == "100"
    assert cold.current_channel_main_exhausted is False
    assert cold.has_more is True

    # Run terminates cleanly with empty-page defaults.
    assert outputs[-1].next_checkpoint.has_more is False


def test_full_lifecycle_main_pagination_then_thread(
    connector: DiscordConnector, helpers: dict[str, AsyncMock]
) -> None:
    """Phase 1 (cold start) -> phase 2 (multi-page main) -> phase 3a (active enum)
    -> phase 3b (archived enum, single page) -> phase 4 (thread page)
    -> phase 5 (rollover) -> done."""
    helpers["list"].return_value = ["100"]
    main_page1 = [_make_doc(1000 - i) for i in range(100)]
    main_page2 = [_make_doc(900 - i) for i in range(20)]
    thread_page = [_make_doc(200 + i) for i in range(50)]
    helpers["fetch"].side_effect = [
        (main_page1, [], "901", 100),  # main page 1, full
        (main_page2, [], "881", 20),  # main page 2, partial -> main exhausted
        (thread_page, [], "200", 50),  # thread page, partial -> thread done
    ]
    helpers["active"].return_value = ["1001"]
    # Single archived page below the page-size threshold -> archived done.
    helpers["archived"].return_value = ([], None)

    outputs = load_everything_from_checkpoint_connector_from_checkpoint(
        connector, 0, _END, connector.build_dummy_checkpoint()
    )

    # outputs[0]: cold start (no docs, channel "100" selected).
    assert outputs[0].items == []
    assert outputs[0].next_checkpoint.current_channel_id == "100"

    # outputs[1]: main page 1 (full -> still in main phase).
    assert sum(isinstance(y, Document) for y in outputs[1].items) == 100
    assert outputs[1].next_checkpoint.current_channel_main_exhausted is False

    # outputs[2]: main page 2 (partial -> main exhausted).
    assert sum(isinstance(y, Document) for y in outputs[2].items) == 20
    assert outputs[2].next_checkpoint.current_channel_main_exhausted is True

    # The second main-page call must use the cursor returned by the first page
    # as `before_snowflake`; this is what guarantees pages chain newest->oldest.
    second_call_args, _ = helpers["fetch"].call_args_list[1]
    assert second_call_args[2] == 901

    # outputs[3]: phase 3a active-thread enumeration. Archived cursor is primed.
    assert outputs[3].items == []
    assert outputs[3].next_checkpoint.current_channel_thread_ids == ["1001"]
    assert outputs[3].next_checkpoint.current_thread_id is None
    assert outputs[3].next_checkpoint.archived_thread_cursor == ""

    # outputs[4]: phase 3b archived enumeration (one partial page -> done).
    assert outputs[4].items == []
    assert outputs[4].next_checkpoint.current_channel_thread_ids == ["1001"]
    assert outputs[4].next_checkpoint.archived_thread_cursor is None
    assert outputs[4].next_checkpoint.current_thread_id == "1001"

    # outputs[5]: thread page.
    assert sum(isinstance(y, Document) for y in outputs[5].items) == 50
    assert outputs[5].next_checkpoint.current_thread_id is None
    # Cursor for the exhausted thread is dropped to bound the map.
    assert "1001" not in outputs[5].next_checkpoint.thread_completion_map

    # outputs[6]: rollover -> done.
    assert outputs[6].items == []
    assert outputs[6].next_checkpoint.has_more is False
    assert outputs[6].next_checkpoint.current_channel_id is None
    # Channel cursor is dropped on rollover.
    assert "100" not in outputs[6].next_checkpoint.channel_completion_map


def test_resume_from_primed_mid_state_checkpoint(
    connector: DiscordConnector, helpers: dict[str, AsyncMock]
) -> None:
    """Validates both the main-channel cursor and the thread cursor are
    correctly forwarded as `before=` to the page fetcher."""
    # Active thread "1001" returns a sub-full page (1 message), which exhausts it.
    # "1002" then returns an empty page and is also exhausted; rollover follows.
    helpers["fetch"].return_value = ([_make_doc(50)], [], "50", 1)

    initial = _make_cp(
        channel_completion_map={"100": "999"},
        current_channel_main_exhausted=True,
        current_channel_thread_ids=["1001", "1002"],
        thread_completion_map={"1001": "777"},
        current_thread_id="1001",
    )
    outputs = load_everything_from_checkpoint_connector_from_checkpoint(
        connector, 0, _END, initial
    )

    # First fetch invocation drives the active thread "1001" with cursor "777".
    args, _ = helpers["fetch"].call_args_list[0]
    # Signature: (token, channel_or_thread_id, before_snowflake, after, before_time)
    assert args[1] == 1001
    assert args[2] == 777

    # After the first cycle, "1001" is exhausted so its cursor is dropped.
    after_thread1 = outputs[0].next_checkpoint
    assert "1001" not in after_thread1.thread_completion_map
    # Main-channel cursor was preserved untouched.
    assert after_thread1.channel_completion_map["100"] == "999"
    # Thread queue advanced.
    assert after_thread1.current_thread_id == "1002"


def test_main_channel_forbidden_skips_channel(
    connector: DiscordConnector, helpers: dict[str, AsyncMock]
) -> None:
    helpers["fetch"].side_effect = [
        _forbidden(),  # channel "100" main fetch denied (permanent)
        _EMPTY_PAGE,  # channel "200" main fetch returns empty
    ]

    initial = _make_cp(
        channel_ids=["100", "200"],
        channel_completion_map={"100": "555"},
    )
    outputs = load_everything_from_checkpoint_connector_from_checkpoint(
        connector, 0, _END, initial
    )

    # First cycle yields a ConnectorFailure for channel "100".
    failure = outputs[0].items[0]
    assert isinstance(failure, ConnectorFailure)
    assert failure.failed_entity is not None
    assert failure.failed_entity.entity_id == "100"

    after_failure = outputs[0].next_checkpoint
    # Both flags set so phases 2 and 3 fall through; rollover next cycle.
    assert after_failure.current_channel_main_exhausted is True
    assert after_failure.current_channel_thread_ids == []
    # Cursor preserved on failure path so a later run can retry.
    assert after_failure.channel_completion_map["100"] == "555"

    # Run terminates after walking through "200".
    assert outputs[-1].next_checkpoint.has_more is False


def test_per_message_failure_does_not_stop_page(
    connector: DiscordConnector, helpers: dict[str, AsyncMock]
) -> None:
    docs = [_make_doc(i) for i in (5, 4)]
    failure = ConnectorFailure(
        failed_document=DocumentFailure(document_id="DISCORD_3"),
        failure_message="boom",
    )
    helpers["fetch"].side_effect = [
        (docs, [failure], "3", 3),  # sub-full page on channel "100"
    ]

    outputs = load_everything_from_checkpoint_connector_from_checkpoint(
        connector, 0, _END, _make_cp()
    )

    # First cycle yields 2 docs + 1 per-document failure.
    assert sum(isinstance(y, Document) for y in outputs[0].items) == 2
    assert sum(isinstance(y, ConnectorFailure) for y in outputs[0].items) == 1


def test_per_thread_failure_advances_to_next_thread(
    connector: DiscordConnector, helpers: dict[str, AsyncMock]
) -> None:
    helpers["fetch"].side_effect = [
        _forbidden(),  # thread "1001" forbidden
        _EMPTY_PAGE,  # thread "1002" empty -> exhausted
    ]

    initial = _make_cp(
        channel_completion_map={"100": "10"},
        current_channel_main_exhausted=True,
        current_channel_thread_ids=["1001", "1002"],
        current_thread_id="1001",
    )
    outputs = load_everything_from_checkpoint_connector_from_checkpoint(
        connector, 0, _END, initial
    )

    # First cycle yields a per-thread ConnectorFailure for "1001".
    failure = outputs[0].items[0]
    assert isinstance(failure, ConnectorFailure)
    assert failure.failed_entity is not None
    assert failure.failed_entity.entity_id == "1001"
    assert outputs[0].next_checkpoint.current_thread_id == "1002"


def test_thread_enumeration_forbidden_skips_threads(
    connector: DiscordConnector, helpers: dict[str, AsyncMock]
) -> None:
    """If `_enumerate_active_threads` raises, surface a channel-level failure
    and set `current_channel_thread_ids = []` so the next cycle rolls over."""
    helpers["active"].side_effect = [
        _forbidden(),  # enumeration on channel "100" forbidden
        [],  # enumeration on channel "200" returns no threads
    ]

    initial = _make_cp(
        channel_ids=["100", "200"],
        current_channel_id="100",
        current_channel_main_exhausted=True,
        current_channel_thread_ids=None,
    )
    outputs = load_everything_from_checkpoint_connector_from_checkpoint(
        connector, 0, _END, initial
    )

    # First cycle: enumeration failure -> channel-level failure surfaced.
    failure = outputs[0].items[0]
    assert isinstance(failure, ConnectorFailure)
    assert failure.failed_entity is not None
    assert failure.failed_entity.entity_id == "100"
    # Empty list (not None) ensures phase 3a won't re-run; archived cursor stays
    # None so phase 3b is also skipped; phase 5 rollover is next.
    assert outputs[0].next_checkpoint.current_channel_thread_ids == []
    assert outputs[0].next_checkpoint.archived_thread_cursor is None

    # Second cycle: rollover to channel "200".
    rolled = outputs[1].next_checkpoint
    assert rolled.current_channel_id == "200"
    assert rolled.current_channel_main_exhausted is False
    assert rolled.current_channel_thread_ids is None


def test_transient_error_retries_then_propagates(
    connector: DiscordConnector, helpers: dict[str, AsyncMock]
) -> None:
    """A transient HTTPException (5xx) bubbling out of the helper means the
    in-helper retry budget was exhausted. The connector must let it propagate
    so the framework retries the attempt from the persisted checkpoint rather
    than silently advancing the cursor past data that could be retried."""
    helpers["fetch"].side_effect = _http_exception(503)

    initial = _make_cp()
    with pytest.raises(HTTPException):
        load_everything_from_checkpoint_connector_from_checkpoint(
            connector, 0, _END, initial
        )


def test_archived_thread_enumeration_paginates_across_cycles(
    connector: DiscordConnector, helpers: dict[str, AsyncMock]
) -> None:
    """Archived-thread enumeration drains one page per cycle: a channel with
    250 archived threads needs 1 cycle for active + 3 cycles for archived
    (100/100/50) before phase 4 starts."""
    active_ids = [str(1_000_000), str(1_000_001)]
    helpers["active"].return_value = active_ids

    page_size = connector_module._ARCHIVED_THREADS_PAGE_SIZE
    page1_ids = [str(900_000 - i) for i in range(page_size)]
    page2_ids = [str(800_000 - i) for i in range(page_size)]
    page3_ids = [str(700_000 - i) for i in range(50)]
    helpers["archived"].side_effect = [
        (page1_ids, "800001"),  # full page -> more remain
        (page2_ids, "700001"),  # full page -> more remain
        (page3_ids, "699951"),  # partial page -> archived done
    ]

    initial = _make_cp(
        channel_ids=["100"],
        current_channel_id="100",
        current_channel_main_exhausted=True,
        current_channel_thread_ids=None,
    )
    outputs = load_everything_from_checkpoint_connector_from_checkpoint(
        connector, 0, _END, initial
    )

    # Cycle 0: phase 3a — active threads enumerated, archived cursor primed.
    cycle0 = outputs[0].next_checkpoint
    assert cycle0.current_channel_thread_ids == active_ids
    assert cycle0.archived_thread_cursor == ""
    assert cycle0.current_thread_id is None

    # Cycle 1: phase 3b first archived page (full -> cursor advances).
    cycle1 = outputs[1].next_checkpoint
    assert cycle1.current_channel_thread_ids == active_ids + page1_ids
    assert cycle1.archived_thread_cursor == "800001"
    assert cycle1.current_thread_id is None

    # Cycle 2: phase 3b second archived page (full -> cursor advances).
    cycle2 = outputs[2].next_checkpoint
    assert cycle2.current_channel_thread_ids == active_ids + page1_ids + page2_ids
    assert cycle2.archived_thread_cursor == "700001"
    assert cycle2.current_thread_id is None

    # Cycle 3: phase 3b third archived page (partial -> archived done; first
    # thread queued for phase 4).
    cycle3 = outputs[3].next_checkpoint
    expected_ids = active_ids + page1_ids + page2_ids + page3_ids
    assert cycle3.current_channel_thread_ids == expected_ids
    assert cycle3.archived_thread_cursor is None
    assert cycle3.current_thread_id == active_ids[0]

    # Confirm cursor plumbing: the second archived page request used the cursor
    # returned by the first page as `before_snowflake`.
    second_call_args, _ = helpers["archived"].call_args_list[1]
    # Signature: (token, channel_id, before_snowflake)
    assert second_call_args[2] == 800001

    # The full run terminates cleanly (each thread drains via the empty-page
    # default for `helpers["fetch"]`).
    assert outputs[-1].next_checkpoint.has_more is False
