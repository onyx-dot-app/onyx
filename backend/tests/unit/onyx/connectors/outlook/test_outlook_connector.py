"""The Outlook connector walk: mailboxes, folders, delta pages, conversations.

The gateway is autospecced, so these tests drive the real checkpoint state
machine and document assembly against the gateway's plain models.
"""

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, call, create_autospec, patch

import pytest

from onyx.configs.app_configs import OUTLOOK_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD
from onyx.connectors.connector_runner import ConnectorRunner
from onyx.connectors.exceptions import ConnectorValidationError, CredentialInvalidError
from onyx.connectors.microsoft_utils.drive_items import SizeCapExceeded
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftAuthError as OutlookAuthError,
)
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftGraphError as OutlookGraphError,
)
from onyx.connectors.models import (
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    SlimDocument,
)
from onyx.connectors.outlook import connector as connector_module
from onyx.connectors.outlook.connector import (
    ATTACHMENT_EXTRACTION_TIMEOUT_SECONDS,
    CONVERSATION_FETCH_LIMIT,
    EVENT_DOCUMENT_ID_PREFIX,
    FILTERED_DELTA_CAP,
    MAX_ATTACHMENT_READS_PER_CONVERSATION,
    MAX_ATTACHMENT_TEXT_PER_CONVERSATION,
    MAX_ATTACHMENTS_PER_MESSAGE,
    MAX_MESSAGES_PER_CONVERSATION,
    SLIM_BATCH_SIZE,
    OutlookCheckpoint,
    OutlookConnector,
    attachment_skip_reason,
    build_conversation_document,
    build_event_document,
    calendar_node_id,
    conversation_document_id,
    event_document_id,
    extract_attachment_text,
    indexable_messages,
    mailbox_node_id,
)
from onyx.connectors.outlook.models import (
    OutlookDeltaPage,
    OutlookEvent,
    OutlookEventPage,
    OutlookFolder,
    OutlookFolderPage,
    OutlookMailboxPage,
    OutlookMessagePage,
    OutlookRecipient,
)
from onyx.connectors.outlook.source_operations import OutlookSourceOperations
from onyx.db.enums import HierarchyNodeType
from onyx.utils.process_isolation import IsolatedProcessError
from tests.unit.onyx.connectors.outlook.outlook_api_shapes import (
    CONVERSATION_ID,
    INBOX_ID,
    MAILBOX_ADDRESS,
    RECEIVED,
    attachment,
    change,
    event,
    folder,
    graph_error,
    mailbox,
    message,
)

CONNECTOR_MODULE = "onyx.connectors.outlook.connector"

JUNK_ID = "folder-junk"
DELETED_ID = "folder-deleted"
DELETED_CHILD_ID = "folder-deleted-2024"
HIDDEN_ID = "folder-hidden"
HIDDEN_CHILD_ID = "folder-hidden-child"
ARCHIVE_ID = "folder-archive"
PROJECTS_ID = "folder-projects"
SEARCH_ID = "folder-search"

START = int((RECEIVED - timedelta(days=1)).timestamp())
END = int((RECEIVED + timedelta(days=1)).timestamp())


def _connector(gateway: MagicMock, **kwargs: Any) -> OutlookConnector:
    connector = OutlookConnector(**kwargs)
    connector._ops = gateway
    return connector


def _well_known(*, mailbox_id: str, name: str) -> OutlookFolder | None:
    del mailbox_id
    return {
        "junkemail": folder(id=JUNK_ID, display_name="Junk Email"),
        "deleteditems": folder(id=DELETED_ID, display_name="Deleted Items"),
    }.get(name)


def _child_folders(
    *,
    mailbox_id: str,
    parent_folder_id: str | None = None,
    page_size: int = 250,
    next_link: str | None = None,
) -> OutlookFolderPage:
    del mailbox_id, page_size, next_link
    children = {
        None: [
            folder(child_folder_count=1),
            folder(id=JUNK_ID, display_name="Junk Email"),
            folder(id=DELETED_ID, display_name="Deleted Items", child_folder_count=1),
            folder(id=SEARCH_ID, display_name="Digests", is_search_folder=True),
            folder(
                id=HIDDEN_ID,
                display_name="Quick Step Settings",
                is_hidden=True,
                child_folder_count=1,
            ),
            folder(id=ARCHIVE_ID, display_name="Archive"),
        ],
        INBOX_ID: [
            folder(id=PROJECTS_ID, display_name="Projects", parent_folder_id=INBOX_ID)
        ],
        DELETED_ID: [
            folder(
                id=DELETED_CHILD_ID, display_name="2024", parent_folder_id=DELETED_ID
            )
        ],
        HIDDEN_ID: [
            folder(id=HIDDEN_CHILD_ID, display_name="Cache", parent_folder_id=HIDDEN_ID)
        ],
    }
    return OutlookFolderPage(folders=children.get(parent_folder_id, []))


def _delta(
    *,
    mailbox_id: str,
    folder_id: str,
    received_after: datetime | None = None,
    page_size: int = 100,
    next_link: str | None = None,
) -> OutlookDeltaPage:
    del mailbox_id, received_after, page_size, next_link
    if folder_id != INBOX_ID:
        return OutlookDeltaPage(changes=[])
    return OutlookDeltaPage(
        changes=[
            change(),
            # A deletion Graph reports with the conversation it belonged to.
            change(id="msg-removed", removed=True, conversation_id="conv-removed"),
            # A row Graph reports without any conversation.
            change(id="msg-no-conversation", conversation_id=None),
            change(id="msg-2"),
            change(
                id="msg-late",
                conversation_id="conv-late",
                received_at=RECEIVED + timedelta(days=2),
            ),
            # A read-state row for mail older than the window, which Graph
            # reports whatever the filter says.
            change(
                id="msg-old",
                conversation_id="conv-old",
                received_at=RECEIVED - timedelta(days=30),
            ),
        ]
    )


def _happy_gateway() -> MagicMock:
    gateway = create_autospec(OutlookSourceOperations, instance=True)
    gateway.resolve_mailbox.return_value = mailbox()
    gateway.list_mailbox_users.return_value = OutlookMailboxPage(mailboxes=[mailbox()])
    gateway.probe_mailbox.return_value = folder()
    gateway.get_well_known_folder.side_effect = _well_known
    gateway.list_child_folders.side_effect = _child_folders
    gateway.fetch_folder_delta_page.side_effect = _delta
    gateway.fetch_conversation_messages_page.return_value = OutlookMessagePage(
        messages=[
            message(id="msg-2", received_at=RECEIVED + timedelta(hours=1)),
            message(),
            message(id="msg-junk", parent_folder_id=JUNK_ID),
            message(id="msg-trashed-deep", parent_folder_id=DELETED_CHILD_ID),
            message(id="msg-hidden-deep", parent_folder_id=HIDDEN_CHILD_ID),
            message(id="msg-draft", is_draft=True),
        ]
    )
    gateway.list_message_attachments.return_value = []
    gateway.fetch_calendar_delta_page.return_value = OutlookEventPage(events=[])
    return gateway


def _attachment_gateway() -> MagicMock:
    """The happy gateway whose newest message carries a mixed bag of attachments."""
    gateway = _happy_gateway()
    gateway.fetch_conversation_messages_page.return_value = OutlookMessagePage(
        messages=[
            message(
                id="msg-2",
                received_at=RECEIVED + timedelta(hours=1),
                has_attachments=True,
            ),
            message(),
        ]
    )
    gateway.list_message_attachments.return_value = [
        attachment(name="report.docx"),
        attachment(id="att-inline", name="logo.png", is_inline=True),
        attachment(id="att-item", name="Fwd: reminder", is_file=False),
        attachment(id="att-zip", name="build.zip"),
        attachment(
            id="att-huge",
            name="huge.pdf",
            size=OUTLOOK_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD + 1,
        ),
    ]
    gateway.download_attachment.return_value = b"PK"
    return gateway


def _step(
    connector: OutlookConnector,
    checkpoint: OutlookCheckpoint,
    include_permissions: bool = False,
) -> tuple[list[Document | HierarchyNode | ConnectorFailure], OutlookCheckpoint]:
    items: list[Document | HierarchyNode | ConnectorFailure] = []
    load = (
        connector.load_from_checkpoint_with_perm_sync
        if include_permissions
        else connector.load_from_checkpoint
    )
    generator = load(START, END, checkpoint)
    while True:
        try:
            items.append(next(generator))
        except StopIteration as stop:
            return items, stop.value


def _run(
    connector: OutlookConnector, include_permissions: bool = False
) -> list[Document | HierarchyNode | ConnectorFailure]:
    """Drive the walk to completion, round-tripping the checkpoint as JSON each
    step the way the indexing pipeline persists it."""
    checkpoint = connector.build_dummy_checkpoint()
    collected: list[Document | HierarchyNode | ConnectorFailure] = []
    for _ in range(50):
        items, checkpoint = _step(connector, checkpoint, include_permissions)
        collected.extend(items)
        checkpoint = connector.validate_checkpoint_json(checkpoint.model_dump_json())
        if not checkpoint.has_more:
            return collected
    raise AssertionError("walk did not finish in 50 steps")


def _folder_checkpoint(**overrides: Any) -> OutlookCheckpoint:
    """A checkpoint parked on the Inbox of an opened mailbox."""
    fields: dict[str, Any] = {
        "has_more": True,
        "mailboxes": [],
        "current_mailbox": mailbox(),
        "folders": [],
        "current_folder": folder(),
    }
    return OutlookCheckpoint(**(fields | overrides))


def test_walk_yields_hierarchy_then_one_document_per_conversation() -> None:
    gateway = _happy_gateway()
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])

    items = _run(connector)

    nodes = [item for item in items if isinstance(item, HierarchyNode)]
    docs = [item for item in items if isinstance(item, Document)]
    assert not [item for item in items if isinstance(item, ConnectorFailure)]

    root = mailbox_node_id(mailbox())
    assert [(n.raw_node_id, n.raw_parent_id, n.node_type) for n in nodes] == [
        (root, None, HierarchyNodeType.MAILBOX),
        (INBOX_ID, root, HierarchyNodeType.FOLDER),
        (ARCHIVE_ID, root, HierarchyNodeType.FOLDER),
        (PROJECTS_ID, INBOX_ID, HierarchyNodeType.FOLDER),
    ]

    assert [doc.id for doc in docs] == [
        conversation_document_id(mailbox(), CONVERSATION_ID)
    ]
    gateway.fetch_conversation_messages_page.assert_called_once_with(
        mailbox_id=mailbox().id, conversation_id=CONVERSATION_ID, next_link=None
    )


def test_walk_skips_removed_old_late_and_repeated_changes() -> None:
    gateway = _happy_gateway()

    _run(_connector(gateway, mailboxes=[MAILBOX_ADDRESS]))

    conversations = [
        call.kwargs["conversation_id"]
        for call in gateway.fetch_conversation_messages_page.call_args_list
    ]
    assert conversations == [CONVERSATION_ID]


def test_walk_filters_delta_by_the_poll_window_start() -> None:
    gateway = _happy_gateway()

    _run(_connector(gateway, mailboxes=[MAILBOX_ADDRESS]))

    first_delta = gateway.fetch_folder_delta_page.call_args_list[0]
    assert first_delta.kwargs["received_after"] == datetime.fromtimestamp(
        START, tz=timezone.utc
    )


def test_walk_excludes_junk_deleted_hidden_and_search_folders() -> None:
    gateway = _happy_gateway()

    _run(_connector(gateway, mailboxes=[MAILBOX_ADDRESS]))

    walked = {
        call.kwargs["folder_id"]
        for call in gateway.fetch_folder_delta_page.call_args_list
    }
    assert walked == {INBOX_ID, ARCHIVE_ID, PROJECTS_ID}


def test_configured_folder_names_are_excluded_case_insensitively() -> None:
    gateway = _happy_gateway()

    _run(_connector(gateway, mailboxes=[MAILBOX_ADDRESS], excluded_folders=["archive"]))

    walked = {
        call.kwargs["folder_id"]
        for call in gateway.fetch_folder_delta_page.call_args_list
    }
    assert ARCHIVE_ID not in walked


def test_excluded_subtrees_are_descended_so_their_folder_ids_are_known() -> None:
    gateway = _happy_gateway()
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])
    checkpoint = connector.build_dummy_checkpoint()

    _, checkpoint = _step(connector, checkpoint)
    _, checkpoint = _step(connector, checkpoint)

    assert set(checkpoint.excluded_folder_ids) == {
        JUNK_ID,
        DELETED_ID,
        DELETED_CHILD_ID,
        HIDDEN_ID,
        HIDDEN_CHILD_ID,
    }


def test_document_drops_excluded_and_draft_messages_and_keeps_order() -> None:
    gateway = _happy_gateway()

    docs = [
        d
        for d in _run(_connector(gateway, mailboxes=[MAILBOX_ADDRESS]))
        if isinstance(d, Document)
    ]

    doc = docs[0]
    assert len(doc.sections) == 2
    first_text = doc.sections[0].text or ""
    assert first_text.startswith("From: Alice <alice@contoso.com>")
    assert "Hello team" in first_text
    assert doc.semantic_identifier == "Quarterly plan"
    assert doc.doc_created_at == RECEIVED
    assert doc.doc_updated_at == RECEIVED + timedelta(hours=1)
    assert doc.parent_hierarchy_raw_node_id == INBOX_ID
    assert doc.metadata == {"mailbox": MAILBOX_ADDRESS, "message_count": "2"}
    assert [o.email for o in doc.primary_owners or []] == [MAILBOX_ADDRESS]
    assert [o.email for o in doc.secondary_owners or []] == ["bob@contoso.com"]


def test_conversation_paging_continues_past_excluded_messages() -> None:
    """Drafts and trashed replies among the newest messages must not displace
    older indexable ones."""
    gateway = _happy_gateway()
    newest = [
        message(
            id=f"draft-{i}", is_draft=True, received_at=RECEIVED + timedelta(hours=i)
        )
        for i in range(60)
    ] + [
        message(id=f"kept-{i}", received_at=RECEIVED + timedelta(minutes=i))
        for i in range(40)
    ]
    older = [
        message(id=f"old-{i}", received_at=RECEIVED - timedelta(minutes=i))
        for i in range(70)
    ]
    gateway.fetch_conversation_messages_page.side_effect = [
        OutlookMessagePage(messages=newest, next_link="https://graph/messages?p=2"),
        OutlookMessagePage(messages=older),
    ]
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])

    items, _ = _step(connector, _folder_checkpoint())

    docs = [item for item in items if isinstance(item, Document)]
    assert len(docs) == 1
    assert len(docs[0].sections) == MAX_MESSAGES_PER_CONVERSATION
    assert docs[0].doc_updated_at == RECEIVED + timedelta(minutes=39)
    assert gateway.fetch_conversation_messages_page.call_count == 2


def test_conversation_paging_stops_at_the_fetch_limit() -> None:
    gateway = _happy_gateway()
    drafts = [message(id=f"draft-{i}", is_draft=True) for i in range(100)]
    gateway.fetch_conversation_messages_page.return_value = OutlookMessagePage(
        messages=drafts, next_link="https://graph/messages?more"
    )
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])

    items, _ = _step(connector, _folder_checkpoint())

    assert items == []
    assert gateway.fetch_conversation_messages_page.call_count == (
        CONVERSATION_FETCH_LIMIT // 100
    )


def test_conversation_fetch_limit_cuts_the_last_page_before_filtering() -> None:
    """The budget counts raw messages, so an indexable message just past it is
    not kept even when it shares a page with messages inside it."""
    gateway = _happy_gateway()
    drafts = [message(id=f"draft-{i}", is_draft=True) for i in range(99)]
    last_page = [
        message(id="draft-last", is_draft=True),
        message(id="just-past-the-budget"),
    ]
    pages = [
        OutlookMessagePage(
            messages=drafts + [message(id="draft-99", is_draft=True)], next_link="p"
        )
        for _ in range(CONVERSATION_FETCH_LIMIT // 100 - 1)
    ]
    pages.append(OutlookMessagePage(messages=drafts, next_link="p"))
    pages.append(OutlookMessagePage(messages=last_page))
    gateway.fetch_conversation_messages_page.side_effect = pages
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])

    items, _ = _step(connector, _folder_checkpoint())

    assert items == []


def test_unresolved_configured_mailbox_is_a_recorded_failure() -> None:
    gateway = _happy_gateway()
    gateway.resolve_mailbox.return_value = None

    items = _run(_connector(gateway, mailboxes=["ghost@contoso.com"]))

    failures = [item for item in items if isinstance(item, ConnectorFailure)]
    assert len(failures) == 1
    assert failures[0].failed_entity is not None
    assert failures[0].failed_entity.entity_id == "ghost@contoso.com"


def test_failed_address_lookup_fails_the_attempt_instead_of_dropping_it() -> None:
    gateway = _happy_gateway()
    gateway.resolve_mailbox.side_effect = graph_error(503, "ServiceUnavailable")

    with pytest.raises(Exception, match="ServiceUnavailable"):
        _run(_connector(gateway, mailboxes=[MAILBOX_ADDRESS]))


def test_failures_are_yielded_only_once_every_address_resolved() -> None:
    """A lookup that raises after an unresolved address must not have yielded
    that address's failure, or the retry would record it twice."""
    gateway = _happy_gateway()
    gateway.resolve_mailbox.side_effect = [None, graph_error(503, "ServiceUnavailable")]
    connector = _connector(gateway, mailboxes=["ghost@contoso.com", MAILBOX_ADDRESS])
    generator = connector.load_from_checkpoint(
        START, END, connector.build_dummy_checkpoint()
    )

    with pytest.raises(Exception, match="ServiceUnavailable"):
        next(generator)


def test_denied_mailbox_is_a_failure_when_named_and_a_skip_otherwise() -> None:
    gateway = _happy_gateway()
    gateway.probe_mailbox.side_effect = graph_error(403)

    named = _run(_connector(gateway, mailboxes=[MAILBOX_ADDRESS]))
    assert [type(item) for item in named] == [ConnectorFailure]

    gateway.probe_mailbox.side_effect = graph_error(403)
    every = _run(_connector(gateway))
    assert every == []


def test_denied_folder_listing_is_treated_like_a_denied_mailbox() -> None:
    gateway = _happy_gateway()
    gateway.list_child_folders.side_effect = graph_error(403)

    items = _run(_connector(gateway, mailboxes=[MAILBOX_ADDRESS]))

    # No hierarchy node goes out for a mailbox whose tree was never complete.
    assert [type(item) for item in items] == [ConnectorFailure]
    gateway.fetch_folder_delta_page.assert_not_called()


def test_denied_delta_stops_the_mailbox_after_one_failure() -> None:
    gateway = _happy_gateway()
    gateway.fetch_folder_delta_page.side_effect = graph_error(403)

    items = _run(_connector(gateway, mailboxes=[MAILBOX_ADDRESS]))

    failures = [item for item in items if isinstance(item, ConnectorFailure)]
    assert len(failures) == 1
    assert gateway.fetch_folder_delta_page.call_count == 1


def test_unexpected_probe_error_fails_the_run_and_keeps_the_mailbox_queued() -> None:
    gateway = _happy_gateway()
    gateway.probe_mailbox.side_effect = graph_error(500, "InternalServerError")
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])
    _, checkpoint = _step(connector, connector.build_dummy_checkpoint())

    with pytest.raises(Exception, match="InternalServerError"):
        _step(connector, checkpoint)

    # The retry resumes from this checkpoint, so the mailbox must still be there.
    assert checkpoint.mailboxes == [mailbox()]
    assert checkpoint.current_mailbox is None


def test_addresses_naming_the_same_mailbox_are_walked_once() -> None:
    gateway = _happy_gateway()

    items = _run(
        _connector(gateway, mailboxes=[MAILBOX_ADDRESS, f"alias-of-{MAILBOX_ADDRESS}"])
    )

    docs = [item for item in items if isinstance(item, Document)]
    assert len(docs) == 1
    assert gateway.probe_mailbox.call_count == 1


def test_users_repeated_across_listing_pages_are_walked_once() -> None:
    gateway = _happy_gateway()
    gateway.list_mailbox_users.side_effect = [
        OutlookMailboxPage(mailboxes=[mailbox()], next_link="https://graph/users?p=2"),
        OutlookMailboxPage(mailboxes=[mailbox()]),
    ]

    items = _run(_connector(gateway))

    docs = [item for item in items if isinstance(item, Document)]
    assert len(docs) == 1
    assert gateway.probe_mailbox.call_count == 1


def test_user_listing_that_never_ends_stops_the_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(connector_module, "MAX_MAILBOX_LISTING_PAGES", 2)
    gateway = _happy_gateway()
    gateway.list_mailbox_users.return_value = OutlookMailboxPage(
        mailboxes=[mailbox()], next_link="https://graph/users?again"
    )

    with pytest.raises(RuntimeError, match="2 pages"):
        _run(_connector(gateway))

    assert gateway.list_mailbox_users.call_count == 2


def test_conversation_tracking_is_capped_per_mailbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Past the cap the oldest thread is forgotten first, so a busy thread stays
    deduplicated while the checkpoint stays bounded."""
    monkeypatch.setattr(connector_module, "MAX_TRACKED_CONVERSATIONS_PER_MAILBOX", 1)
    gateway = _happy_gateway()
    gateway.fetch_folder_delta_page.side_effect = None
    gateway.fetch_folder_delta_page.return_value = OutlookDeltaPage(
        changes=[
            change(),
            change(id="msg-a2"),
            change(id="msg-b1", conversation_id="conv-b"),
            change(id="msg-b2", conversation_id="conv-b"),
            change(id="msg-a3"),
        ]
    )
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])
    checkpoint = _folder_checkpoint()

    _step(connector, checkpoint)

    rebuilt = [
        call.kwargs["conversation_id"]
        for call in gateway.fetch_conversation_messages_page.call_args_list
    ]
    assert rebuilt == [CONVERSATION_ID, "conv-b", CONVERSATION_ID]
    assert checkpoint.seen_conversation_ids == {CONVERSATION_ID: None}


def test_failure_part_way_through_a_page_leaves_the_page_uncounted() -> None:
    """The replayed page must not count twice toward the filtered delta cap."""
    gateway = _happy_gateway()
    gateway.fetch_folder_delta_page.side_effect = None
    gateway.fetch_folder_delta_page.return_value = OutlookDeltaPage(
        changes=[change(), change(id="msg-b", conversation_id="conv-b")],
        next_link="https://graph/delta?more",
    )
    gateway.fetch_conversation_messages_page.side_effect = [
        OutlookMessagePage(messages=[message()]),
        OutlookAuthError("invalid_client", "secret expired"),
    ]
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])
    checkpoint = _folder_checkpoint(folder_change_count=4997)

    with pytest.raises(OutlookAuthError):
        _step(connector, checkpoint)

    assert checkpoint.folder_change_count == 4997
    assert checkpoint.delta_next_link is None
    assert checkpoint.seen_conversation_ids == {CONVERSATION_ID: None}


def test_expired_delta_state_restarts_the_folder_round() -> None:
    gateway = _happy_gateway()
    gateway.fetch_folder_delta_page.side_effect = graph_error(410, "SyncStateNotFound")
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])
    checkpoint = _folder_checkpoint(
        delta_next_link="https://graph/delta?$skiptoken=old", folder_change_count=7
    )

    items, checkpoint = _step(connector, checkpoint)

    assert items == []
    assert checkpoint.current_folder == folder()
    assert checkpoint.delta_next_link is None
    assert checkpoint.folder_change_count == 0


def test_vanished_folder_is_skipped() -> None:
    gateway = _happy_gateway()
    gateway.fetch_folder_delta_page.side_effect = graph_error(404, "ErrorItemNotFound")
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])

    items, checkpoint = _step(connector, _folder_checkpoint())

    assert items == []
    assert checkpoint.current_folder is None
    assert checkpoint.current_mailbox == mailbox()


def test_folder_that_fills_the_filtered_cap_is_reread_without_the_filter() -> None:
    gateway = _happy_gateway()
    windows: list[datetime | None] = []

    def capped_delta(**kwargs: Any) -> OutlookDeltaPage:
        windows.append(kwargs["received_after"])
        if kwargs["received_after"] is None:
            return OutlookDeltaPage(changes=[change()])
        return OutlookDeltaPage(
            changes=[
                change(id=f"msg-{i}", conversation_id=None)
                for i in range(FILTERED_DELTA_CAP)
            ]
        )

    gateway.fetch_folder_delta_page.side_effect = capped_delta
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])

    items, checkpoint = _step(connector, _folder_checkpoint())
    assert items == []
    assert checkpoint.current_folder == folder()
    assert checkpoint.folder_unfiltered is True

    items, checkpoint = _step(connector, checkpoint)
    assert [type(item) for item in items] == [Document]
    assert checkpoint.current_folder is None
    assert windows == [datetime.fromtimestamp(START, tz=timezone.utc), None]


def test_conversation_fetch_refusal_is_a_document_failure() -> None:
    gateway = _happy_gateway()
    gateway.fetch_conversation_messages_page.side_effect = graph_error(
        404, "ErrorItemNotFound"
    )

    items = _run(_connector(gateway, mailboxes=[MAILBOX_ADDRESS]))

    failures = [item for item in items if isinstance(item, ConnectorFailure)]
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == conversation_document_id(
        mailbox(), CONVERSATION_ID
    )


@pytest.mark.parametrize("status", [429, 503, 509, None])
def test_transient_conversation_fetch_failure_keeps_the_checkpoint(
    status: int | None,
) -> None:
    """A recorded failure would let the poll window move past the mail, so a
    throttled or dropped call fails the attempt with the conversation unseen."""
    gateway = _happy_gateway()
    gateway.fetch_conversation_messages_page.side_effect = OutlookGraphError(
        status, "ServiceUnavailable", "busy"
    )
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])
    checkpoint = _folder_checkpoint()

    with pytest.raises(OutlookGraphError):
        _step(connector, checkpoint)

    assert checkpoint.seen_conversation_ids == {}
    assert checkpoint.delta_next_link is None


def test_indexable_messages_drop_drafts_and_excluded_folders() -> None:
    kept = message()

    assert indexable_messages(
        [message(is_draft=True), message(id="junk", parent_folder_id=JUNK_ID), kept],
        {JUNK_ID},
    ) == [kept]


def test_conversation_keeps_only_the_newest_messages() -> None:
    messages = [
        message(id=f"msg-{i}", received_at=RECEIVED + timedelta(minutes=i))
        for i in range(MAX_MESSAGES_PER_CONVERSATION + 5)
    ]

    doc = build_conversation_document(mailbox(), CONVERSATION_ID, messages)

    assert doc is not None
    assert len(doc.sections) == MAX_MESSAGES_PER_CONVERSATION
    assert doc.doc_updated_at == messages[-1].received_at
    assert doc.doc_created_at == messages[5].received_at


def test_conversation_without_messages_is_dropped() -> None:
    assert build_conversation_document(mailbox(), CONVERSATION_ID, []) is None


def test_conversation_without_a_subject_gets_a_placeholder_and_root_parent() -> None:
    doc = build_conversation_document(
        mailbox(),
        CONVERSATION_ID,
        [message(subject=None, parent_folder_id=None, sender=None, to_recipients=[])],
    )

    assert doc is not None
    assert doc.semantic_identifier == "(no subject)"
    assert doc.parent_hierarchy_raw_node_id == mailbox_node_id(mailbox())
    assert doc.primary_owners == []


def test_senders_are_not_repeated_as_secondary_owners() -> None:
    bob = OutlookRecipient(address="bob@contoso.com", name="Bob")
    alice = OutlookRecipient(address=MAILBOX_ADDRESS, name="Alice")
    doc = build_conversation_document(
        mailbox(),
        CONVERSATION_ID,
        [
            message(sender=alice, to_recipients=[bob]),
            message(id="msg-2", sender=bob, to_recipients=[alice]),
        ],
    )

    assert doc is not None
    assert sorted(o.email or "" for o in doc.primary_owners or []) == [
        MAILBOX_ADDRESS,
        "bob@contoso.com",
    ]
    assert doc.secondary_owners == []


def test_validation_maps_token_refusal_to_invalid_credential() -> None:
    gateway = _happy_gateway()
    gateway.check_token.side_effect = OutlookAuthError("invalid_client", "bad secret")

    with pytest.raises(CredentialInvalidError):
        _connector(gateway).validate_connector_settings()


@pytest.mark.parametrize(
    ("status", "code"),
    [(404, "MailboxNotEnabledForRESTAPI"), (423, "ErrorMailboxLocked")],
)
def test_validation_lists_unreachable_configured_mailboxes(
    status: int, code: str
) -> None:
    """A denied, missing or locked mailbox is the mailbox's own problem, so it is
    named in the validation error rather than failing the check outright."""
    gateway = _happy_gateway()
    gateway.resolve_mailbox.side_effect = [None, mailbox(id="user-2")]
    gateway.probe_mailbox.side_effect = graph_error(status, code)

    with pytest.raises(ConnectorValidationError) as exc_info:
        _connector(
            gateway, mailboxes=["ghost@contoso.com", "unlicensed@contoso.com"]
        ).validate_connector_settings()

    assert "ghost@contoso.com (no such user)" in str(exc_info.value)
    assert f"unlicensed@contoso.com ({code})" in str(exc_info.value)


def test_validation_in_every_mailbox_mode_probes_the_user_listing() -> None:
    gateway = _happy_gateway()

    _connector(gateway).validate_connector_settings()

    gateway.list_mailbox_users.assert_called_once_with(page_size=1)
    gateway.resolve_mailbox.assert_not_called()


def test_mismatched_national_cloud_hosts_are_rejected_at_construction() -> None:
    with pytest.raises(ConnectorValidationError):
        OutlookConnector(
            graph_api_host="https://graph.microsoft.us",
            authority_host="https://login.microsoftonline.com",
        )


def test_credentials_before_provider_is_a_programming_error() -> None:
    with pytest.raises(ConnectorMissingCredentialError):
        _ = OutlookConnector().ops


# ---------------------------------------------------------------------------
# attachments
# ---------------------------------------------------------------------------


def _extraction(text: str) -> Callable[..., str]:
    """A stand-in for the isolated extraction that asserts what it was asked to
    run and applies the cap the way the child would."""

    def run(fn: Callable[..., str], *args: Any, timeout: float, **kwargs: Any) -> str:
        assert fn is extract_attachment_text
        assert timeout == ATTACHMENT_EXTRACTION_TIMEOUT_SECONDS
        assert kwargs == {}
        data, name, cap = args
        assert isinstance(data, bytes) and name
        return text[:cap]

    return run


def _attachment_connector(gateway: MagicMock) -> OutlookConnector:
    return _connector(gateway, mailboxes=[MAILBOX_ADDRESS], include_attachments=True)


def test_extract_attachment_text_uses_the_local_parsers_and_caps() -> None:
    assert extract_attachment_text(b"  hello world  ", "note.txt", 5) == "hello"
    with pytest.raises(ValueError):
        extract_attachment_text(b"\x00\x01\x02", "blob.bin", 10)


def test_attachment_text_follows_its_message_and_skips_the_rest() -> None:
    gateway = _attachment_gateway()
    connector = _attachment_connector(gateway)

    with patch(
        f"{CONNECTOR_MODULE}.run_in_isolated_process",
        side_effect=_extraction("Quarterly numbers"),
    ):
        items, _ = _step(connector, _folder_checkpoint())

    docs = [item for item in items if isinstance(item, Document)]
    texts = [section.text or "" for section in docs[0].sections]
    assert len(texts) == 3
    assert texts[1].startswith("From: Alice")
    assert texts[2] == "Attachment: report.docx\n\nQuarterly numbers"
    assert docs[0].sections[2].link == message().web_link
    gateway.list_message_attachments.assert_called_once_with(
        mailbox_id=mailbox().id, message_id="msg-2", limit=MAX_ATTACHMENTS_PER_MESSAGE
    )
    # Only the plain file attachment is worth a download: inline images, item
    # attachments, unsupported types and oversize files are skipped unread.
    gateway.download_attachment.assert_called_once_with(
        mailbox_id=mailbox().id,
        message_id="msg-2",
        attachment_id="att-1",
        cap=OUTLOOK_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD,
    )


def test_attachments_are_not_read_by_default() -> None:
    gateway = _attachment_gateway()
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])

    items, _ = _step(connector, _folder_checkpoint())

    assert len([item for item in items if isinstance(item, Document)]) == 1
    gateway.list_message_attachments.assert_not_called()


def test_attachment_over_the_cap_or_refused_is_skipped() -> None:
    gateway = _attachment_gateway()
    gateway.download_attachment.side_effect = SizeCapExceeded("during_download")
    connector = _attachment_connector(gateway)

    items, _ = _step(connector, _folder_checkpoint())
    docs = [item for item in items if isinstance(item, Document)]
    assert len(docs[0].sections) == 2

    gateway.download_attachment.side_effect = graph_error(404, "ErrorItemNotFound")
    items, _ = _step(connector, _folder_checkpoint())
    docs = [item for item in items if isinstance(item, Document)]
    assert len(docs[0].sections) == 2


def test_throttled_attachment_read_keeps_the_checkpoint() -> None:
    gateway = _attachment_gateway()
    gateway.download_attachment.side_effect = graph_error(429, "TooManyRequests")
    connector = _attachment_connector(gateway)
    checkpoint = _folder_checkpoint()

    with pytest.raises(OutlookGraphError):
        _step(connector, checkpoint)

    assert checkpoint.seen_conversation_ids == {}


def test_refused_attachment_listing_keeps_the_message_text() -> None:
    gateway = _attachment_gateway()
    gateway.list_message_attachments.side_effect = graph_error(403)
    connector = _attachment_connector(gateway)

    items, _ = _step(connector, _folder_checkpoint())

    docs = [item for item in items if isinstance(item, Document)]
    assert len(docs[0].sections) == 2
    gateway.download_attachment.assert_not_called()


def test_attachment_extraction_that_hangs_or_crashes_is_skipped() -> None:
    gateway = _attachment_gateway()
    connector = _attachment_connector(gateway)

    with patch(
        f"{CONNECTOR_MODULE}.run_in_isolated_process",
        side_effect=IsolatedProcessError("timed out"),
    ):
        items, _ = _step(connector, _folder_checkpoint())

    docs = [item for item in items if isinstance(item, Document)]
    assert len(docs[0].sections) == 2


def test_attachment_text_is_capped_per_conversation() -> None:
    gateway = _attachment_gateway()
    gateway.list_message_attachments.return_value = [
        attachment(id=f"att-{n}", name=f"part-{n}.txt") for n in range(3)
    ]
    connector = _attachment_connector(gateway)
    # Each attachment expands to over half the budget, so the second one is
    # truncated and the third is never downloaded.
    text = "x" * (MAX_ATTACHMENT_TEXT_PER_CONVERSATION * 3 // 5)

    with patch(
        f"{CONNECTOR_MODULE}.run_in_isolated_process", side_effect=_extraction(text)
    ):
        items, _ = _step(connector, _folder_checkpoint())

    docs = [item for item in items if isinstance(item, Document)]
    kept = [
        len(section.text or "") - len("Attachment: part-0.txt\n\n")
        for section in docs[0].sections[2:]
    ]
    assert sum(kept) == MAX_ATTACHMENT_TEXT_PER_CONVERSATION
    assert gateway.download_attachment.call_count == 2


def test_failed_extractions_spend_the_read_budget() -> None:
    gateway = _attachment_gateway()
    gateway.list_message_attachments.return_value = [
        attachment(id=f"att-{n}", name=f"part-{n}.txt")
        for n in range(MAX_ATTACHMENT_READS_PER_CONVERSATION + 5)
    ]
    connector = _attachment_connector(gateway)

    with patch(
        f"{CONNECTOR_MODULE}.run_in_isolated_process",
        side_effect=IsolatedProcessError("timed out"),
    ):
        items, _ = _step(connector, _folder_checkpoint())

    docs = [item for item in items if isinstance(item, Document)]
    assert len(docs[0].sections) == 2
    assert (
        gateway.download_attachment.call_count == MAX_ATTACHMENT_READS_PER_CONVERSATION
    )


def test_attachment_skip_reasons() -> None:
    assert attachment_skip_reason(attachment()) is None
    assert attachment_skip_reason(attachment(is_file=False)) == "not a file attachment"
    assert attachment_skip_reason(attachment(is_inline=True)) == "inline attachment"
    assert (
        attachment_skip_reason(attachment(name="tool.exe")) == "unsupported file type"
    )
    assert (
        attachment_skip_reason(
            attachment(size=OUTLOOK_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD + 1)
        )
        == "over the size threshold"
    )


# ---------------------------------------------------------------------------
# pruning
# ---------------------------------------------------------------------------


def _slim_ids(batches: list[list[SlimDocument | HierarchyNode]]) -> list[str]:
    return [
        item.id for batch in batches for item in batch if isinstance(item, SlimDocument)
    ]


def test_slim_docs_list_every_conversation_without_reading_bodies() -> None:
    gateway = _happy_gateway()
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])

    batches = list(connector.retrieve_all_slim_docs())

    nodes = [item for item in batches[0] if isinstance(item, HierarchyNode)]
    assert [n.raw_node_id for n in nodes] == [
        mailbox_node_id(mailbox()),
        INBOX_ID,
        ARCHIVE_ID,
        PROJECTS_ID,
    ]
    # The unfiltered delta lists every conversation, old and late alike, and
    # the removed and conversation-less rows are skipped.
    assert sorted(_slim_ids(batches)) == sorted(
        conversation_document_id(mailbox(), cid)
        for cid in (CONVERSATION_ID, "conv-late", "conv-old")
    )
    assert all(
        item.parent_hierarchy_raw_node_id is None
        for batch in batches
        for item in batch
        if isinstance(item, SlimDocument)
    )
    gateway.fetch_conversation_messages_page.assert_not_called()
    assert all(
        "received_after" not in call.kwargs
        for call in gateway.fetch_folder_delta_page.call_args_list
    )


def test_slim_docs_abort_when_a_configured_address_matches_nobody() -> None:
    """A stale address is a configuration problem. Skipping it would prune
    every conversation of the mailbox behind it."""
    gateway = _happy_gateway()
    gateway.resolve_mailbox.side_effect = [mailbox(), None]
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS, "ghost@contoso.com"])

    with pytest.raises(ConnectorValidationError, match="ghost@contoso.com"):
        list(connector.retrieve_all_slim_docs())

    gateway.probe_mailbox.assert_not_called()


def test_slim_docs_abort_when_a_folder_vanishes_mid_walk() -> None:
    """A folder deleted between the tree listing and its own children request
    answers 404 too. Skipping the mailbox would prune all of its live mail."""
    gateway = _happy_gateway()

    def child_folders(**kwargs: Any) -> OutlookFolderPage:
        if kwargs["parent_folder_id"] == INBOX_ID:
            raise graph_error(404, "ErrorItemNotFound")
        return _child_folders(**kwargs)

    gateway.list_child_folders.side_effect = child_folders
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])

    with pytest.raises(OutlookGraphError):
        list(connector.retrieve_all_slim_docs())


def test_slim_docs_skip_a_vanished_mailbox_and_abort_on_anything_else() -> None:
    gateway = _happy_gateway()
    gateway.probe_mailbox.side_effect = graph_error(404, "MailboxNotEnabledForRESTAPI")

    assert (
        list(_connector(gateway, mailboxes=[MAILBOX_ADDRESS]).retrieve_all_slim_docs())
        == []
    )

    gateway.probe_mailbox.side_effect = graph_error(403)
    with pytest.raises(OutlookGraphError):
        list(_connector(gateway, mailboxes=[MAILBOX_ADDRESS]).retrieve_all_slim_docs())


def test_slim_docs_abort_when_delta_state_expires_mid_folder() -> None:
    """Ids already yielded from the expired round cannot be retracted, so a
    restart could keep a since-deleted conversation alive. Aborting deletes
    nothing and the next prune starts clean."""
    gateway = _happy_gateway()
    inbox_pages: list[OutlookDeltaPage | OutlookGraphError] = [
        OutlookDeltaPage(changes=[change()], next_link="https://graph/delta?p=2"),
        graph_error(410, "SyncStateNotFound"),
    ]

    def delta(**kwargs: Any) -> OutlookDeltaPage:
        if kwargs["folder_id"] != INBOX_ID:
            return OutlookDeltaPage(changes=[])
        page = inbox_pages.pop(0)
        if isinstance(page, OutlookGraphError):
            raise page
        return page

    gateway.fetch_folder_delta_page.side_effect = delta
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])

    with pytest.raises(OutlookGraphError):
        list(connector.retrieve_all_slim_docs())


def test_slim_docs_batch_and_report_progress() -> None:
    gateway = _happy_gateway()
    gateway.fetch_folder_delta_page.side_effect = lambda **kwargs: OutlookDeltaPage(
        changes=[
            change(id=f"m-{i}", conversation_id=f"{kwargs['folder_id']}-conv-{i}")
            for i in range(SLIM_BATCH_SIZE + 1)
        ]
    )
    callback = MagicMock()
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])

    batches = list(connector.retrieve_all_slim_docs(callback=callback))

    # Three walked folders of 501 each, batched across folder boundaries.
    slim_batches = [b for b in batches if isinstance(b[0], SlimDocument)]
    assert [len(b) for b in slim_batches] == [SLIM_BATCH_SIZE] * 3 + [3]
    assert (
        callback.progress.call_args_list
        == [call("outlook_slim_docs", SLIM_BATCH_SIZE + 1)] * 3
    )


def test_slim_docs_follow_delta_pages_by_their_link() -> None:
    gateway = _happy_gateway()
    pages_by_link: dict[str | None, OutlookDeltaPage] = {
        None: OutlookDeltaPage(changes=[change()], next_link="https://graph/delta?p=2"),
        "https://graph/delta?p=2": OutlookDeltaPage(
            changes=[], next_link="https://graph/delta?p=3"
        ),
        "https://graph/delta?p=3": OutlookDeltaPage(
            changes=[change(id="msg-2", conversation_id="conv-2")]
        ),
    }

    def delta(**kwargs: Any) -> OutlookDeltaPage:
        if kwargs["folder_id"] != INBOX_ID:
            return OutlookDeltaPage(changes=[])
        return pages_by_link[kwargs["next_link"]]

    gateway.fetch_folder_delta_page.side_effect = delta
    callback = MagicMock()
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])

    ids = _slim_ids(list(connector.retrieve_all_slim_docs(callback=callback)))

    assert ids == [
        conversation_document_id(mailbox(), CONVERSATION_ID),
        conversation_document_id(mailbox(), "conv-2"),
    ]
    inbox_progress = [
        c for c in callback.progress.call_args_list if c == call("outlook_slim_docs", 1)
    ]
    assert len(inbox_progress) == 2
    assert call("outlook_slim_docs", 0) in callback.progress.call_args_list


# ---------------------------------------------------------------------------
# calendar
# ---------------------------------------------------------------------------

SERIES_ID = "series-1"


def _calendar_gateway() -> MagicMock:
    """The happy gateway whose calendar holds a single meeting, a recurring
    series seen twice, an exception of that series, and two events to skip."""
    gateway = _happy_gateway()
    gateway.fetch_calendar_delta_page.return_value = OutlookEventPage(
        events=[
            event(),
            event(id="occ-1", event_type="occurrence", series_master_id=SERIES_ID),
            event(id="occ-2", event_type="occurrence", series_master_id=SERIES_ID),
            event(
                id="exc-1",
                event_type="exception",
                series_master_id=SERIES_ID,
                subject="Standup moved",
            ),
            event(id="evt-cancelled", is_cancelled=True),
            event(id="evt-private", sensitivity="private"),
        ]
    )
    gateway.get_event.return_value = event(
        id=SERIES_ID,
        event_type="seriesMaster",
        subject="Standup",
        recurrence="every week on monday from 2026-01-05",
    )
    return gateway


def _calendar_connector(gateway: MagicMock, **kwargs: Any) -> OutlookConnector:
    return _connector(
        gateway, mailboxes=[MAILBOX_ADDRESS], include_calendar=True, **kwargs
    )


def _event_doc_ids(
    items: list[Document | HierarchyNode | ConnectorFailure],
) -> list[str]:
    return [
        item.id
        for item in items
        if isinstance(item, Document) and item.id.startswith(EVENT_DOCUMENT_ID_PREFIX)
    ]


def test_calendar_is_off_by_default() -> None:
    gateway = _calendar_gateway()

    items = _run(_connector(gateway, mailboxes=[MAILBOX_ADDRESS]))

    gateway.fetch_calendar_delta_page.assert_not_called()
    nodes = [item for item in items if isinstance(item, HierarchyNode)]
    assert calendar_node_id(mailbox()) not in [n.raw_node_id for n in nodes]


def test_calendar_follows_the_folders_with_one_document_per_event_or_series() -> None:
    gateway = _calendar_gateway()

    items = _run(_calendar_connector(gateway))

    nodes = [item for item in items if isinstance(item, HierarchyNode)]
    assert (calendar_node_id(mailbox()), mailbox_node_id(mailbox())) in [
        (n.raw_node_id, n.raw_parent_id) for n in nodes
    ]
    docs = [item for item in items if isinstance(item, Document)]
    assert [doc.id for doc in docs] == [
        conversation_document_id(mailbox(), CONVERSATION_ID),
        event_document_id(mailbox(), "evt-1"),
        event_document_id(mailbox(), SERIES_ID),
        event_document_id(mailbox(), "exc-1"),
    ]
    # Two occurrences, one master read, one document carrying the pattern.
    gateway.get_event.assert_called_once_with(
        mailbox_id=mailbox().id, event_id=SERIES_ID
    )
    series = docs[2]
    assert series.semantic_identifier == "Standup"
    assert "Repeats: every week on monday from 2026-01-05" in (
        series.sections[0].text or ""
    )
    assert series.parent_hierarchy_raw_node_id == calendar_node_id(mailbox())
    assert not [item for item in items if isinstance(item, ConnectorFailure)]


def test_calendar_window_comes_from_the_configured_days() -> None:
    gateway = _calendar_gateway()

    _run(_calendar_connector(gateway, calendar_past_days=10, calendar_future_days=5))

    kwargs = gateway.fetch_calendar_delta_page.call_args.kwargs
    assert kwargs["window_end"] - kwargs["window_start"] == timedelta(days=15)
    assert kwargs["next_link"] is None


def test_negative_calendar_days_are_rejected() -> None:
    with pytest.raises(ConnectorValidationError):
        OutlookConnector(calendar_past_days=-1)


def test_calendar_skips_events_untouched_since_the_poll_window_opened() -> None:
    gateway = _calendar_gateway()
    gateway.fetch_calendar_delta_page.return_value = OutlookEventPage(
        events=[
            event(id="old", last_modified_at=RECEIVED - timedelta(days=30)),
            event(id="fresh"),
            event(id="undated", last_modified_at=None),
        ]
    )

    items = _run(_calendar_connector(gateway))

    assert _event_doc_ids(items) == [
        event_document_id(mailbox(), "fresh"),
        event_document_id(mailbox(), "undated"),
    ]


def test_untouched_events_entering_the_front_of_the_window_are_indexed() -> None:
    """The future edge moves with time, so an old event can appear in the view
    for the first time without having changed."""
    gateway = _calendar_gateway()
    stale = RECEIVED - timedelta(days=30)
    gateway.fetch_calendar_delta_page.return_value = OutlookEventPage(
        events=[
            event(
                id="entered",
                last_modified_at=stale,
                start_at=RECEIVED + timedelta(days=9),
                end_at=RECEIVED + timedelta(days=9, hours=1),
            ),
            event(
                id="already-inside",
                last_modified_at=stale,
                start_at=RECEIVED + timedelta(days=2),
                end_at=RECEIVED + timedelta(days=2, hours=1),
            ),
        ]
    )

    items = _run(_calendar_connector(gateway, calendar_future_days=10))

    # START is one day before RECEIVED, so the front of the window at the
    # previous poll sat nine days after it.
    assert _event_doc_ids(items) == [event_document_id(mailbox(), "entered")]


def test_calendar_pages_follow_their_link_then_the_mailbox_finishes() -> None:
    gateway = _calendar_gateway()
    gateway.fetch_calendar_delta_page.side_effect = [
        OutlookEventPage(events=[event(id="page-1")], next_link="https://graph/next"),
        OutlookEventPage(events=[event(id="page-2")]),
    ]

    items = _run(_calendar_connector(gateway))

    assert [
        c.kwargs["next_link"] for c in gateway.fetch_calendar_delta_page.call_args_list
    ] == [None, "https://graph/next"]
    assert _event_doc_ids(items) == [
        event_document_id(mailbox(), "page-1"),
        event_document_id(mailbox(), "page-2"),
    ]


def test_calendar_round_restarts_when_graph_drops_its_state() -> None:
    gateway = _calendar_gateway()
    gateway.fetch_calendar_delta_page.side_effect = graph_error(
        410, "SyncStateNotFound"
    )
    connector = _calendar_connector(gateway)
    checkpoint = _folder_checkpoint(
        current_folder=None, calendar_next_link="https://graph/next"
    )

    items, checkpoint = _step(connector, checkpoint)

    assert items == []
    assert checkpoint.calendar_next_link is None
    assert checkpoint.calendar_done is False
    assert checkpoint.current_mailbox == mailbox()


def test_denied_calendar_is_a_failure_when_named_and_a_skip_otherwise() -> None:
    gateway = _calendar_gateway()
    gateway.fetch_calendar_delta_page.side_effect = graph_error(403)

    named = _run(_calendar_connector(gateway))
    failures = [item for item in named if isinstance(item, ConnectorFailure)]
    assert len(failures) == 1
    assert failures[0].failed_entity is not None
    assert failures[0].failed_entity.entity_id == f"{MAILBOX_ADDRESS} calendar"
    # The mail was indexed all the same.
    assert [doc.id for doc in named if isinstance(doc, Document)] == [
        conversation_document_id(mailbox(), CONVERSATION_ID)
    ]

    every = _run(_connector(gateway, include_calendar=True))
    assert not [item for item in every if isinstance(item, ConnectorFailure)]


def test_throttled_calendar_read_keeps_the_checkpoint() -> None:
    gateway = _calendar_gateway()
    gateway.fetch_calendar_delta_page.side_effect = graph_error(429, "TooManyRequests")
    connector = _calendar_connector(gateway)
    checkpoint = _folder_checkpoint(current_folder=None)

    with pytest.raises(OutlookGraphError):
        _step(connector, checkpoint)

    assert checkpoint.calendar_done is False


def test_unreadable_series_master_skips_the_series_once() -> None:
    gateway = _calendar_gateway()
    gateway.get_event.side_effect = graph_error(404, "ErrorItemNotFound")

    items = _run(_calendar_connector(gateway))

    assert event_document_id(mailbox(), SERIES_ID) not in _event_doc_ids(items)
    gateway.get_event.assert_called_once()


def test_excluded_series_master_is_not_indexed() -> None:
    """Occurrence rows mirror their master, but the master's text is what gets
    indexed, so it is checked as well."""
    gateway = _calendar_gateway()
    gateway.get_event.return_value = event(
        id=SERIES_ID, event_type="seriesMaster", sensitivity="private"
    )

    items = _run(_calendar_connector(gateway))

    assert event_document_id(mailbox(), SERIES_ID) not in _event_doc_ids(items)
    gateway.get_event.assert_called_once()


def test_rejected_token_on_a_series_master_keeps_the_checkpoint() -> None:
    """A 401 is the app's trouble, not the series', so nothing is skipped."""
    gateway = _calendar_gateway()
    gateway.get_event.side_effect = graph_error(401, "InvalidAuthenticationToken")
    connector = _calendar_connector(gateway)
    checkpoint = _folder_checkpoint(current_folder=None)

    with pytest.raises(OutlookGraphError):
        _step(connector, checkpoint)

    assert checkpoint.calendar_done is False
    assert checkpoint.seen_series_ids == set()


def test_event_document_carries_the_meeting_facts() -> None:
    doc = build_event_document(mailbox(), event())

    text = doc.sections[0].text or ""
    assert text == (
        "When: 2026-09-02 14:00 to 15:00 UTC\n"
        "Where: Room 4\n"
        "Organizer: Alice <alice@contoso.com>\n"
        "Attendees: Bob <bob@contoso.com>, Alice <alice@contoso.com>\n"
        "Subject: Quarterly review\n\n"
        "Agenda: numbers"
    )
    assert doc.sections[0].link == "https://outlook.office365.com/calendar/item/evt-1"
    assert [o.email for o in doc.primary_owners or []] == [MAILBOX_ADDRESS]
    # The organizer is not listed twice.
    assert [o.email for o in doc.secondary_owners or []] == ["bob@contoso.com"]
    assert doc.metadata == {
        "mailbox": MAILBOX_ADDRESS,
        "recurring": "false",
        "start": "2026-09-02T14:00:00+00:00",
        "end": "2026-09-02T15:00:00+00:00",
        "location": "Room 4",
    }
    assert doc.doc_updated_at == RECEIVED


def test_all_day_and_multi_day_events_read_as_dates() -> None:
    day = datetime(2026, 9, 2, tzinfo=timezone.utc)
    one_day = event(is_all_day=True, start_at=day, end_at=day + timedelta(days=1))
    three_days = event(is_all_day=True, start_at=day, end_at=day + timedelta(days=3))
    overnight = event(
        start_at=day + timedelta(hours=22), end_at=day + timedelta(hours=25)
    )

    def when(e: OutlookEvent) -> str:
        text = build_event_document(mailbox(), e).sections[0].text or ""
        return text.splitlines()[0]

    assert when(one_day) == "When: 2026-09-02 (all day)"
    assert when(three_days) == "When: 2026-09-02 to 2026-09-04 (all day)"
    assert when(overnight) == "When: 2026-09-02 22:00 to 2026-09-03 01:00 UTC"


def test_all_day_dates_are_read_in_the_zone_they_were_scheduled_in() -> None:
    """Graph converts an all-day event's midnights to UTC, so a Tokyo
    September 2 starts on September 1 in UTC."""
    tokyo = event(
        is_all_day=True,
        start_at=datetime(2026, 9, 1, 15, 0, tzinfo=timezone.utc),
        end_at=datetime(2026, 9, 2, 15, 0, tzinfo=timezone.utc),
        time_zone="Tokyo Standard Time",
    )
    unknown_zone = event(
        is_all_day=True,
        start_at=datetime(2026, 9, 1, 15, 0, tzinfo=timezone.utc),
        end_at=datetime(2026, 9, 2, 15, 0, tzinfo=timezone.utc),
        time_zone="tzone://Microsoft/Custom",
    )

    def when(e: OutlookEvent) -> str:
        text = build_event_document(mailbox(), e).sections[0].text or ""
        return text.splitlines()[0]

    assert when(tokyo) == "When: 2026-09-02 (all day)"
    # Graph also reports IANA names.
    assert when(event(**{**tokyo.model_dump(), "time_zone": "Asia/Tokyo"})) == (
        "When: 2026-09-02 (all day)"
    )
    # An unmapped zone falls back to the UTC dates rather than guess.
    assert when(unknown_zone) == "When: 2026-09-01 (all day)"


def test_event_time_names_the_zone_it_was_scheduled_in() -> None:
    scheduled = event(time_zone="Eastern Standard Time")

    text = build_event_document(mailbox(), scheduled).sections[0].text or ""

    assert text.splitlines()[0] == (
        "When: 2026-09-02 14:00 to 15:00 UTC (scheduled in Eastern Standard Time)"
    )


def test_slim_docs_list_events_collapsed_to_their_series() -> None:
    gateway = _calendar_gateway()
    connector = _calendar_connector(gateway)

    batches = list(connector.retrieve_all_slim_docs())

    nodes = [
        item for batch in batches for item in batch if isinstance(item, HierarchyNode)
    ]
    assert calendar_node_id(mailbox()) in [n.raw_node_id for n in nodes]
    event_ids = [
        i for i in _slim_ids(batches) if i.startswith(EVENT_DOCUMENT_ID_PREFIX)
    ]
    assert event_ids == [
        event_document_id(mailbox(), "evt-1"),
        event_document_id(mailbox(), SERIES_ID),
        event_document_id(mailbox(), "exc-1"),
    ]
    # One master read per series decides whether the series is listed at all.
    gateway.get_event.assert_called_once_with(
        mailbox_id=mailbox().id, event_id=SERIES_ID
    )


def test_slim_docs_leave_out_a_series_whose_master_is_excluded_or_unreadable() -> None:
    """Indexing writes nothing for such a series, so pruning must not keep it."""
    gateway = _calendar_gateway()
    connector = _calendar_connector(gateway)

    gateway.get_event.return_value = event(
        id=SERIES_ID, event_type="seriesMaster", sensitivity="private"
    )
    ids = _slim_ids(list(connector.retrieve_all_slim_docs()))
    assert event_document_id(mailbox(), SERIES_ID) not in ids
    assert event_document_id(mailbox(), "exc-1") in ids

    gateway.get_event.side_effect = graph_error(404, "ErrorItemNotFound")
    ids = _slim_ids(list(connector.retrieve_all_slim_docs()))
    assert event_document_id(mailbox(), SERIES_ID) not in ids

    gateway.get_event.side_effect = graph_error(401, "InvalidAuthenticationToken")
    with pytest.raises(OutlookGraphError):
        list(connector.retrieve_all_slim_docs())


def test_slim_docs_prune_the_events_of_a_calendar_that_is_gone() -> None:
    """A vanished calendar answers 404 on its first page, like a vanished
    mailbox on its probe, so its events go while the conversations stay."""
    gateway = _calendar_gateway()
    gateway.fetch_calendar_delta_page.side_effect = graph_error(
        404, "ErrorItemNotFound"
    )
    connector = _calendar_connector(gateway)

    ids = _slim_ids(list(connector.retrieve_all_slim_docs()))

    assert conversation_document_id(mailbox(), CONVERSATION_ID) in ids
    assert not [i for i in ids if i.startswith(EVENT_DOCUMENT_ID_PREFIX)]


def test_slim_docs_stop_when_a_calendar_is_refused() -> None:
    """Listing nothing would prune events that only a full re-index brings
    back, so the prune stops and names the grant and the switch."""
    gateway = _calendar_gateway()
    gateway.fetch_calendar_delta_page.side_effect = graph_error(403)
    connector = _calendar_connector(gateway)

    with pytest.raises(ConnectorValidationError, match="Calendars.Read") as info:
        list(connector.retrieve_all_slim_docs())

    assert "Include Calendar" in str(info.value)


def test_slim_docs_stop_when_a_calendar_fails_mid_round_or_is_throttled() -> None:
    """Ids already listed cannot be retracted, so a round that breaks after
    its first page aborts the prune."""
    gateway = _calendar_gateway()
    connector = _calendar_connector(gateway)

    gateway.fetch_calendar_delta_page.side_effect = [
        OutlookEventPage(events=[event()], next_link="https://graph/next"),
        graph_error(404, "ErrorItemNotFound"),
    ]
    with pytest.raises(OutlookGraphError):
        list(connector.retrieve_all_slim_docs())

    gateway.fetch_calendar_delta_page.side_effect = graph_error(429)
    with pytest.raises(OutlookGraphError):
        list(connector.retrieve_all_slim_docs())


def test_slim_docs_deduplicate_events_per_page_only() -> None:
    gateway = _calendar_gateway()
    occurrence = event(id="occ-1", event_type="occurrence", series_master_id=SERIES_ID)
    gateway.fetch_calendar_delta_page.side_effect = [
        OutlookEventPage(
            events=[occurrence, occurrence], next_link="https://graph/next"
        ),
        OutlookEventPage(events=[occurrence]),
    ]
    connector = _calendar_connector(gateway)

    ids = _slim_ids(list(connector.retrieve_all_slim_docs()))

    # The set pruning builds absorbs the repeat, so nothing grows with the
    # size of the calendar to prevent it.
    assert [i for i in ids if i.startswith(EVENT_DOCUMENT_ID_PREFIX)] == [
        event_document_id(mailbox(), SERIES_ID),
        event_document_id(mailbox(), SERIES_ID),
    ]


def test_series_tracking_is_capped_per_mailbox() -> None:
    gateway = _calendar_gateway()
    gateway.fetch_calendar_delta_page.return_value = OutlookEventPage(
        events=[
            event(id="a-1", event_type="occurrence", series_master_id="series-a"),
            event(id="b-1", event_type="occurrence", series_master_id="series-b"),
            event(id="b-2", event_type="occurrence", series_master_id="series-b"),
        ]
    )
    gateway.get_event.side_effect = lambda **kwargs: event(
        id=kwargs["event_id"], event_type="seriesMaster"
    )
    connector = _calendar_connector(gateway)

    with patch(f"{CONNECTOR_MODULE}.MAX_TRACKED_SERIES_PER_MAILBOX", 1):
        items = _run(connector)

    # The first series is remembered, the second is read for each occurrence
    # and its document written twice, which the index absorbs.
    assert [c.kwargs["event_id"] for c in gateway.get_event.call_args_list] == [
        "series-a",
        "series-b",
        "series-b",
    ]
    assert _event_doc_ids(items) == [
        event_document_id(mailbox(), "series-a"),
        event_document_id(mailbox(), "series-b"),
        event_document_id(mailbox(), "series-b"),
    ]


# ---------------------------------------------------------------------------
# permission sync
# ---------------------------------------------------------------------------


def _readers(item: Document | SlimDocument | HierarchyNode) -> set[str]:
    assert item.external_access is not None
    assert item.external_access.is_public is False
    assert item.external_access.external_user_group_ids == set()
    return item.external_access.external_user_emails


def _assert_each_readership(
    items: Sequence[Document | SlimDocument | HierarchyNode | ConnectorFailure],
) -> None:
    nodes = [i for i in items if isinstance(i, HierarchyNode)]
    assert len(nodes) == 5
    assert all(_readers(n) == {MAILBOX_ADDRESS} for n in nodes)
    by_id = {i.id: i for i in items if isinstance(i, (Document, SlimDocument))}
    assert _readers(by_id[conversation_document_id(mailbox(), CONVERSATION_ID)]) == {
        MAILBOX_ADDRESS
    }
    # The owner, the organizer (the owner here) and the attendees.
    assert _readers(by_id[event_document_id(mailbox(), "evt-1")]) == {
        MAILBOX_ADDRESS,
        "bob@contoso.com",
    }
    assert _readers(by_id[event_document_id(mailbox(), SERIES_ID)]) == {
        MAILBOX_ADDRESS,
        "bob@contoso.com",
    }


def test_perm_sync_slim_docs_carry_each_readership() -> None:
    connector = _calendar_connector(_calendar_gateway())

    items = [i for batch in connector.retrieve_all_slim_docs_perm_sync() for i in batch]

    _assert_each_readership(items)


def test_series_readers_come_from_the_master_in_both_walks() -> None:
    """The series document holds the master's text, so an attendee an
    occurrence row names must not read it unless the master names them too."""
    gateway = _calendar_gateway()
    gateway.fetch_calendar_delta_page.return_value = OutlookEventPage(
        events=[
            event(
                id="occ-1",
                event_type="occurrence",
                series_master_id=SERIES_ID,
                attendees=[OutlookRecipient(address="carol@contoso.com", name="C")],
            )
        ]
    )
    connector = _calendar_connector(gateway)
    series_doc_id = event_document_id(mailbox(), SERIES_ID)

    slim = [i for batch in connector.retrieve_all_slim_docs_perm_sync() for i in batch]
    indexed = _run(connector, include_permissions=True)

    for items in (slim, indexed):
        by_id = {i.id: i for i in items if isinstance(i, (Document, SlimDocument))}
        assert _readers(by_id[series_doc_id]) == {MAILBOX_ADDRESS, "bob@contoso.com"}


def test_perm_sync_indexing_carries_each_readership() -> None:
    """A connector set to Auto Sync Permissions indexes with its readers
    attached, so its documents are searchable before the first sync."""
    items = _run(_calendar_connector(_calendar_gateway()), include_permissions=True)

    _assert_each_readership(items)


def test_runner_indexes_with_permissions_from_the_first_step() -> None:
    """The runner refuses a connector without the permission-aware checkpoint
    walk, which would have blocked the first index of an Auto Sync connector."""
    connector = _calendar_connector(_calendar_gateway())
    runner = ConnectorRunner(
        connector,
        batch_size=100,
        include_permissions=True,
        time_range=(
            datetime.fromtimestamp(START, tz=timezone.utc),
            datetime.fromtimestamp(END, tz=timezone.utc),
        ),
    )

    checkpoint = connector.build_dummy_checkpoint()
    items: list[Document | HierarchyNode] = []
    for _ in range(50):
        for docs, nodes, _failure, next_checkpoint in runner.run(checkpoint):
            items.extend(docs or [])
            items.extend(nodes or [])
            if next_checkpoint is not None:
                checkpoint = next_checkpoint
        if not checkpoint.has_more:
            break

    _assert_each_readership(items)


def test_plain_walks_carry_no_readership() -> None:
    connector = _calendar_connector(_calendar_gateway())

    pruned = [i for batch in connector.retrieve_all_slim_docs() for i in batch]
    indexed = [i for i in _run(connector) if not isinstance(i, ConnectorFailure)]

    assert pruned and all(i.external_access is None for i in pruned)
    assert indexed and all(i.external_access is None for i in indexed)
