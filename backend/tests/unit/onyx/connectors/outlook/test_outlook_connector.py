"""The Outlook connector walk: mailboxes, folders, delta pages, conversations.

The gateway is autospecced, so these tests drive the real checkpoint state
machine and document assembly against the gateway's plain models.
"""

import json
import threading
from collections.abc import Callable, Generator, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, call, create_autospec, patch

import pytest
from pydantic import ValidationError

from onyx.configs.app_configs import OUTLOOK_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD
from onyx.connectors.connector_runner import ConnectorRunner
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    RateLimitTriedTooManyTimesError,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    InsufficientPermissionsError,
)
from onyx.connectors.microsoft_utils.drive_items import SizeCapExceeded
from onyx.connectors.microsoft_utils.entra import EntraGroup
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
from onyx.connectors.outlook.config import OutlookConnectorConfig
from onyx.connectors.outlook.connector import (
    ATTACHMENT_EXTRACTION_TIMEOUT_SECONDS,
    CONVERSATION_FETCH_LIMIT,
    EVENT_DOCUMENT_ID_PREFIX,
    FILTERED_DELTA_CAP,
    MAILBOX_WORKERS,
    MAX_ATTACHMENT_READS_PER_CONVERSATION,
    MAX_ATTACHMENT_TEXT_PER_CONVERSATION,
    MAX_ATTACHMENTS_PER_MESSAGE,
    MAX_MESSAGES_PER_CONVERSATION,
    MAX_TRACKED_SERIES_PER_MAILBOX,
    SLIM_BATCH_SIZE,
    THROTTLED_MESSAGE,
    OutlookCheckpoint,
    OutlookConnector,
    attachment_skip_reason,
    build_event_document,
    build_thread_document,
    calendar_node_id,
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
    OutlookMessage,
    OutlookMessageChange,
    OutlookMessagePage,
    OutlookRecipient,
)
from onyx.connectors.outlook.source_operations import OutlookSourceOperations
from onyx.connectors.outlook.threads import copy_document_id
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
    memory_file_store,
    message,
    thread_doc_id,
)

CONNECTOR_MODULE = "onyx.connectors.outlook.connector"


@pytest.fixture(autouse=True)
def _memory_thread_table() -> Generator[MagicMock, None, None]:
    """The real thread table over a file store kept in memory."""
    store = memory_file_store()
    with patch(
        "onyx.connectors.outlook.threads.get_default_file_store", return_value=store
    ):
        yield store


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
    gateway.fetch_conversation_outline_page.side_effect = _outline_of(gateway)
    gateway.list_message_attachments.return_value = []
    gateway.fetch_calendar_delta_page.return_value = OutlookEventPage(events=[])
    return gateway


def _outline_of(gateway: MagicMock) -> Callable[..., OutlookDeltaPage]:
    """An outline that mirrors whatever the messages page returns for the
    copy, so the two fetches agree unless a test says otherwise."""

    def outline(
        *, mailbox_id: str, conversation_id: str, next_link: str | None = None
    ) -> OutlookDeltaPage:
        del mailbox_id, conversation_id, next_link
        page: OutlookMessagePage = gateway.fetch_conversation_messages_page.return_value
        return OutlookDeltaPage(
            changes=[
                change(
                    id=m.id,
                    internet_message_id=m.internet_message_id,
                    conversation_id=m.conversation_id,
                    parent_folder_id=m.parent_folder_id,
                    received_at=m.received_at,
                    is_draft=m.is_draft,
                )
                for m in page.messages
            ],
            next_link=page.next_link,
        )

    return outline


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
    start: int = START,
) -> tuple[list[Document | HierarchyNode | ConnectorFailure], OutlookCheckpoint]:
    items: list[Document | HierarchyNode | ConnectorFailure] = []
    load = (
        connector.load_from_checkpoint_with_perm_sync
        if include_permissions
        else connector.load_from_checkpoint
    )
    generator = load(start, END, checkpoint)
    while True:
        try:
            items.append(next(generator))
        except StopIteration as stop:
            return items, stop.value


def _run(
    connector: OutlookConnector, include_permissions: bool = False, start: int = START
) -> list[Document | HierarchyNode | ConnectorFailure]:
    """Drive the walk to completion, round-tripping the checkpoint as JSON each
    step the way the indexing pipeline persists it."""
    checkpoint = connector.build_dummy_checkpoint()
    collected: list[Document | HierarchyNode | ConnectorFailure] = []
    for _ in range(50):
        items, checkpoint = _step(connector, checkpoint, include_permissions, start)
        collected.extend(items)
        checkpoint = connector.validate_checkpoint_json(checkpoint.model_dump_json())
        if not checkpoint.has_more:
            return collected
    raise AssertionError("walk did not finish in 50 steps")


def _finish(
    connector: OutlookConnector,
    checkpoint: OutlookCheckpoint,
    include_permissions: bool = False,
) -> list[Document | HierarchyNode | ConnectorFailure]:
    """Drive the walk from the given checkpoint to completion, mutating it in
    place the way a failing step leaves it."""
    collected: list[Document | HierarchyNode | ConnectorFailure] = []
    for _ in range(50):
        items, checkpoint = _step(connector, checkpoint, include_permissions)
        collected.extend(items)
        if not checkpoint.has_more:
            return collected
    raise AssertionError("walk did not finish in 50 steps")


def _build(messages: list[OutlookMessage], **overrides: Any) -> Document | None:
    fields: dict[str, Any] = {
        "document_id": thread_doc_id(CONVERSATION_ID),
        "mailbox": mailbox(),
        "readers": [mailbox()],
    }
    return build_thread_document(messages=messages, **(fields | overrides))


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

    assert [doc.id for doc in docs] == [thread_doc_id(CONVERSATION_ID)]
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


def test_mail_history_cutoff_bounds_a_walk_from_the_beginning() -> None:
    gateway = _happy_gateway()
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS], mail_history_days=30)
    before = datetime.now(timezone.utc) - timedelta(days=30)

    generator = connector.load_from_checkpoint(0, END, _folder_checkpoint())
    with pytest.raises(StopIteration):
        while True:
            next(generator)

    received_after = gateway.fetch_folder_delta_page.call_args.kwargs["received_after"]
    assert before <= received_after <= datetime.now(timezone.utc) - timedelta(days=30)


def test_mail_history_cutoff_never_widens_a_later_poll_window() -> None:
    gateway = _happy_gateway()
    connector = _connector(
        gateway, mailboxes=[MAILBOX_ADDRESS], mail_history_days=100_000
    )

    _step(connector, _folder_checkpoint())

    received_after = gateway.fetch_folder_delta_page.call_args.kwargs["received_after"]
    assert received_after == datetime.fromtimestamp(START, tz=timezone.utc)


def test_config_rejects_a_non_positive_mail_history() -> None:
    with pytest.raises(ValidationError):
        OutlookConnectorConfig(mail_history_days=0)


def test_mail_history_days_must_be_positive() -> None:
    with pytest.raises(ConnectorValidationError):
        OutlookConnector(mail_history_days=0)


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

    assert set(checkpoint.active[0].excluded_folder_ids) == {
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
    assert doc.metadata == {
        "mailbox": MAILBOX_ADDRESS,
        "mailbox_count": "1",
        "message_count": "2",
    }
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

    items = _finish(connector, _folder_checkpoint())

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

    items = _finish(connector, _folder_checkpoint())

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

    items = _finish(connector, _folder_checkpoint())

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


def _group_gateway() -> MagicMock:
    gateway = _happy_gateway()
    gateway.resolve_groups.return_value = [EntraGroup(id="group-1")]
    gateway.list_group_mailbox_users.return_value = OutlookMailboxPage(
        mailboxes=[mailbox()]
    )
    return gateway


def _walked_mailbox_ids(gateway: MagicMock) -> list[str]:
    return [c.kwargs["mailbox_id"] for c in gateway.probe_mailbox.call_args_list]


def test_group_mode_walks_the_group_members_instead_of_every_user() -> None:
    gateway = _group_gateway()
    gateway.list_group_mailbox_users.side_effect = [
        OutlookMailboxPage(mailboxes=[mailbox()], next_link="https://graph/next"),
        OutlookMailboxPage(mailboxes=[mailbox(id="user-2")]),
    ]

    _run(_connector(gateway, mailbox_groups=["Onyx Users"]))

    gateway.resolve_groups.assert_called_once_with(identifier="Onyx Users")
    assert gateway.list_group_mailbox_users.call_args_list == [
        call(group_id="group-1", next_link=None),
        call(group_id="group-1", next_link="https://graph/next"),
    ]
    gateway.list_mailbox_users.assert_not_called()
    assert sorted(_walked_mailbox_ids(gateway)) == sorted([mailbox().id, "user-2"])


def test_named_mailboxes_and_group_members_are_walked_together_once() -> None:
    gateway = _group_gateway()
    gateway.list_group_mailbox_users.return_value = OutlookMailboxPage(
        mailboxes=[mailbox(), mailbox(id="user-2")]
    )

    _run(_connector(gateway, mailboxes=[MAILBOX_ADDRESS], mailbox_groups=["g"]))

    assert sorted(_walked_mailbox_ids(gateway)) == sorted([mailbox().id, "user-2"])


@pytest.mark.parametrize(
    ("matches", "reason"),
    [
        ([], "No group matches Sales"),
        (
            [EntraGroup(id="group-1"), EntraGroup(id="group-2")],
            "More than one group is named Sales",
        ),
    ],
)
def test_group_that_does_not_name_one_group_is_a_recorded_failure(
    matches: list[EntraGroup], reason: str
) -> None:
    gateway = _group_gateway()
    gateway.resolve_groups.return_value = matches

    items = _run(_connector(gateway, mailbox_groups=["Sales"]))

    failures = [item for item in items if isinstance(item, ConnectorFailure)]
    assert len(failures) == 1
    assert failures[0].failed_entity is not None
    assert failures[0].failed_entity.entity_id == "Sales"
    assert reason in failures[0].failure_message
    gateway.list_group_mailbox_users.assert_not_called()
    gateway.list_mailbox_users.assert_not_called()


def test_failed_group_lookup_fails_the_attempt_instead_of_dropping_it() -> None:
    gateway = _group_gateway()
    gateway.resolve_groups.side_effect = graph_error(503, "ServiceUnavailable")

    with pytest.raises(Exception, match="ServiceUnavailable"):
        _run(_connector(gateway, mailbox_groups=["Sales"]))


def test_validation_names_groups_that_do_not_resolve() -> None:
    gateway = _group_gateway()
    gateway.resolve_groups.return_value = []

    with pytest.raises(ConnectorValidationError) as exc_info:
        _connector(gateway, mailbox_groups=["Sales"]).validate_connector_settings()

    assert "No group matches Sales" in str(exc_info.value)
    gateway.list_mailbox_users.assert_not_called()


def test_validation_maps_a_denied_group_read_to_the_group_permission() -> None:
    gateway = _group_gateway()
    gateway.resolve_groups.side_effect = graph_error(403, "Authorization_RequestDenied")

    with pytest.raises(InsufficientPermissionsError, match="GroupMember.Read.All"):
        _connector(gateway, mailbox_groups=["Sales"]).validate_connector_settings()


def test_pruning_lists_a_shared_thread_once_with_every_holder() -> None:
    gateway = _happy_gateway()
    gateway.list_mailbox_users.return_value = OutlookMailboxPage(
        mailboxes=[
            mailbox(id="user-1", address="alice@contoso.com"),
            mailbox(id="user-2", address="bob@contoso.com"),
        ]
    )
    connector = _connector(gateway)

    docs = [
        d
        for batch in connector.retrieve_all_slim_docs_perm_sync()
        for d in batch
        if isinstance(d, SlimDocument)
    ]

    ids = [d.id for d in docs]
    assert len(ids) == len(set(ids))
    shared = next(d for d in docs if d.id == thread_doc_id(CONVERSATION_ID))
    assert shared.external_access is not None
    assert set(shared.external_access.external_user_emails) == {
        "alice@contoso.com",
        "bob@contoso.com",
    }


def test_listing_step_replayed_after_a_failure_rewrites_the_same_page(
    _memory_thread_table: MagicMock,
) -> None:
    gateway = _happy_gateway()
    gateway.fetch_folder_delta_page.side_effect = None
    gateway.fetch_folder_delta_page.return_value = OutlookDeltaPage(
        changes=[change()], next_link="https://graph/delta?more"
    )
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])
    checkpoint = _folder_checkpoint()
    saved = checkpoint.model_copy(deep=True)

    _step(connector, checkpoint)
    # The step's checkpoint was never persisted, so the saved one runs again.
    _step(connector, saved)

    pages = [f for f in _memory_thread_table.files if "listing-" in f]
    assert pages == [f"outlook-threads/{checkpoint.run_id}/listing-0.jsonl"]
    assert saved.listing_pages == 1


def test_thread_table_is_deleted_once_the_walk_finishes(
    _memory_thread_table: MagicMock,
) -> None:
    _run(_connector(_happy_gateway(), mailboxes=[MAILBOX_ADDRESS]))

    assert _memory_thread_table.files == {}


def test_pruning_stops_at_an_unresolved_group() -> None:
    gateway = _group_gateway()
    gateway.resolve_groups.return_value = []
    connector = _connector(gateway, mailbox_groups=["Sales"])

    with pytest.raises(ConnectorValidationError, match="cannot be resolved: Sales"):
        list(connector.retrieve_all_slim_docs())


def test_pruning_drops_mail_older_than_the_history_cutoff() -> None:
    gateway = _happy_gateway()
    gateway.fetch_folder_delta_page.side_effect = None
    now = datetime.now(timezone.utc)
    gateway.fetch_folder_delta_page.return_value = OutlookDeltaPage(
        changes=[
            change(received_at=now - timedelta(days=1)),
            change(
                id="msg-old",
                conversation_id="conv-old",
                received_at=now - timedelta(days=4000),
            ),
        ]
    )
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS], mail_history_days=30)

    ids = [
        d.id
        for batch in connector.retrieve_all_slim_docs()
        for d in batch
        if isinstance(d, SlimDocument)
    ]

    assert thread_doc_id("conv-old") not in ids
    assert thread_doc_id(CONVERSATION_ID) in ids
    assert (
        gateway.fetch_folder_delta_page.call_args.kwargs.get("received_after") is None
    )


def _many_mailbox_gateway(count: int) -> MagicMock:
    gateway = _happy_gateway()
    gateway.list_mailbox_users.return_value = OutlookMailboxPage(
        mailboxes=[mailbox(id=f"user-{n}") for n in range(count)]
    )
    return gateway


def test_mailboxes_are_walked_side_by_side_up_to_the_worker_limit() -> None:
    gateway = _many_mailbox_gateway(MAILBOX_WORKERS + 1)
    connector = _connector(gateway)
    _, checkpoint = _step(connector, connector.build_dummy_checkpoint())

    _, checkpoint = _step(connector, checkpoint)

    assert [cursor.mailbox.id for cursor in checkpoint.active] == [
        f"user-{n}" for n in range(MAILBOX_WORKERS)
    ]
    assert all(cursor.opened for cursor in checkpoint.active)
    assert checkpoint.mailboxes == [mailbox(id=f"user-{MAILBOX_WORKERS}")]


def test_every_mailbox_past_the_worker_limit_is_still_walked() -> None:
    gateway = _many_mailbox_gateway(MAILBOX_WORKERS + 2)

    items = _run(_connector(gateway))

    probed = {c.kwargs["mailbox_id"] for c in gateway.probe_mailbox.call_args_list}
    assert probed == {f"user-{n}" for n in range(MAILBOX_WORKERS + 2)}
    documents = [item for item in items if isinstance(item, Document)]
    assert [doc.id for doc in documents] == [thread_doc_id(CONVERSATION_ID)]


def test_thread_held_by_several_mailboxes_is_built_once_for_all_holders() -> None:
    gateway = _happy_gateway()
    gateway.list_mailbox_users.return_value = OutlookMailboxPage(
        mailboxes=[
            mailbox(id="user-1", address="alice@contoso.com"),
            mailbox(id="user-2", address="bob@contoso.com"),
        ]
    )

    items = _run(_connector(gateway), include_permissions=True)

    documents = [item for item in items if isinstance(item, Document)]
    assert len(documents) == 1
    assert documents[0].metadata["mailbox_count"] == "2"
    assert documents[0].external_access is not None
    assert set(documents[0].external_access.external_user_emails) == {
        "alice@contoso.com",
        "bob@contoso.com",
    }
    assert gateway.fetch_conversation_messages_page.call_count == 1
    assert gateway.fetch_conversation_messages_page.call_args.kwargs["mailbox_id"] == (
        "user-1"
    )


ALICE = mailbox(id="user-1", address="alice@contoso.com")
BOB = mailbox(id="user-2", address="bob@contoso.com")
DAVE = mailbox(id="user-3", address="dave@contoso.com")


def _private_reply_gateway() -> MagicMock:
    """Alice and Bob share a thread. Dave replied to Alice alone, then Alice
    answered Bob. Alice holds three messages, Bob two, Dave one."""
    root = message(id="root", received_at=RECEIVED)
    private = message(
        id="private",
        received_at=RECEIVED + timedelta(hours=1),
        sender=OutlookRecipient(address=DAVE.address, name="Dave"),
        to_recipients=[OutlookRecipient(address=ALICE.address, name="Alice")],
    )
    answer = message(id="answer", received_at=RECEIVED + timedelta(hours=2))
    held: dict[str, list[OutlookMessage]] = {
        ALICE.id: [answer, private, root],
        BOB.id: [answer, root],
        DAVE.id: [private],
    }
    gateway = _happy_gateway()
    gateway.list_mailbox_users.return_value = OutlookMailboxPage(
        mailboxes=[ALICE, BOB, DAVE]
    )

    def delta(*, mailbox_id: str, folder_id: str, **_: Any) -> OutlookDeltaPage:
        if folder_id != INBOX_ID:
            return OutlookDeltaPage(changes=[])
        return OutlookDeltaPage(
            changes=[
                change(
                    id=m.id,
                    conversation_id=m.conversation_id,
                    received_at=m.received_at,
                )
                for m in held[mailbox_id]
            ]
        )

    def messages(*, mailbox_id: str, **_: Any) -> OutlookMessagePage:
        return OutlookMessagePage(messages=held[mailbox_id])

    def outline(*, mailbox_id: str, **_: Any) -> OutlookDeltaPage:
        return OutlookDeltaPage(
            changes=[
                change(
                    id=m.id,
                    conversation_id=m.conversation_id,
                    received_at=m.received_at,
                )
                for m in held[mailbox_id]
            ]
        )

    def find(
        *, mailbox_id: str, internet_message_id: str
    ) -> OutlookMessageChange | None:
        for m in held[mailbox_id]:
            if m.internet_message_id == internet_message_id:
                return change(
                    id=m.id,
                    conversation_id=m.conversation_id,
                    received_at=m.received_at,
                )
        return None

    gateway.fetch_folder_delta_page.side_effect = delta
    gateway.fetch_conversation_messages_page.side_effect = messages
    gateway.fetch_conversation_outline_page.side_effect = outline
    gateway.find_message_by_internet_message_id.side_effect = find
    return gateway


def test_a_poll_writes_documents_for_the_holders_it_did_not_list() -> None:
    """Only Alice's copy changed in the window, so only Alice is listed. Bob
    and Dave are found from the messages' recipients and get the documents a
    full listing would have given them."""
    gateway = _private_reply_gateway()
    list_everyone = gateway.fetch_folder_delta_page.side_effect

    def alice_only(*, mailbox_id: str, **kwargs: Any) -> OutlookDeltaPage:
        if mailbox_id != ALICE.id:
            return OutlookDeltaPage(changes=[])
        return list_everyone(mailbox_id=mailbox_id, **kwargs)

    gateway.fetch_folder_delta_page.side_effect = alice_only

    items = _run(_connector(gateway), include_permissions=True)

    documents = {item.id: item for item in items if isinstance(item, Document)}
    thread = documents[thread_doc_id(CONVERSATION_ID)]
    assert len(thread.sections) == 3
    assert _readers(thread) == {"alice@contoso.com"}
    key = thread.id.split(":", 1)[1]
    assert len(documents[copy_document_id(key, BOB)].sections) == 2
    assert _readers(documents[copy_document_id(key, BOB)]) == {"bob@contoso.com"}
    assert len(documents[copy_document_id(key, DAVE)].sections) == 1
    assert set(documents) == {
        thread.id,
        copy_document_id(key, BOB),
        copy_document_id(key, DAVE),
    }
    assert sorted(
        c.kwargs["mailbox_id"]
        for c in gateway.find_message_by_internet_message_id.call_args_list
    ) == [BOB.id, DAVE.id]


def test_a_poll_skips_an_unlisted_holder_graph_refuses() -> None:
    """Dave's mailbox is refused at the probe, so it was never opened and the
    thread is still built for everyone else without a failure."""
    gateway = _private_reply_gateway()
    list_everyone = gateway.fetch_folder_delta_page.side_effect
    gateway.fetch_folder_delta_page.side_effect = lambda *, mailbox_id, **kw: (
        list_everyone(mailbox_id=mailbox_id, **kw)
        if mailbox_id == ALICE.id
        else OutlookDeltaPage(changes=[])
    )

    def probe(*, mailbox_id: str) -> OutlookFolder:
        if mailbox_id == DAVE.id:
            raise OutlookGraphError(403, "ErrorAccessDenied", "out of scope")
        return folder()

    find_held = gateway.find_message_by_internet_message_id.side_effect

    def find(*, mailbox_id: str, **kw: Any) -> OutlookMessageChange | None:
        if mailbox_id == DAVE.id:
            raise OutlookGraphError(403, "ErrorAccessDenied", "out of scope")
        return find_held(mailbox_id=mailbox_id, **kw)

    gateway.probe_mailbox.side_effect = probe
    gateway.find_message_by_internet_message_id.side_effect = find

    items = _run(_connector(gateway), include_permissions=True)

    documents = {item.id: item for item in items if isinstance(item, Document)}
    key = thread_doc_id(CONVERSATION_ID).split(":", 1)[1]
    assert set(documents) == {
        thread_doc_id(CONVERSATION_ID),
        copy_document_id(key, BOB),
    }
    assert not [item for item in items if isinstance(item, ConnectorFailure)]


def test_an_unlisted_holder_keeps_its_own_folder_exclusions() -> None:
    """Bob's copy of the root sits in his Archive, which the connector
    excludes by name, so his document holds the answer alone."""
    gateway = _private_reply_gateway()
    list_everyone = gateway.fetch_folder_delta_page.side_effect
    gateway.fetch_folder_delta_page.side_effect = lambda *, mailbox_id, **kw: (
        list_everyone(mailbox_id=mailbox_id, **kw)
        if mailbox_id == ALICE.id
        else OutlookDeltaPage(changes=[])
    )
    read_everyone = gateway.fetch_conversation_messages_page.side_effect

    def bobs_root_is_archived(*, mailbox_id: str, **kw: Any) -> OutlookMessagePage:
        page = read_everyone(mailbox_id=mailbox_id, **kw)
        if mailbox_id != BOB.id:
            return page
        return OutlookMessagePage(
            messages=[
                m.model_copy(update={"parent_folder_id": ARCHIVE_ID})
                if m.id == "root"
                else m
                for m in page.messages
            ]
        )

    gateway.fetch_conversation_messages_page.side_effect = bobs_root_is_archived

    items = _run(
        _connector(gateway, excluded_folders=["Archive"]), include_permissions=True
    )

    documents = {item.id: item for item in items if isinstance(item, Document)}
    key = thread_doc_id(CONVERSATION_ID).split(":", 1)[1]
    assert len(documents[copy_document_id(key, BOB)].sections) == 1


def test_a_listing_from_the_beginning_never_looks_for_unlisted_holders() -> None:
    gateway = _private_reply_gateway()

    _run(_connector(gateway), include_permissions=True, start=0)

    gateway.find_message_by_internet_message_id.assert_not_called()


def test_a_private_reply_is_readable_only_by_the_mailboxes_that_hold_it() -> None:
    gateway = _private_reply_gateway()

    items = _run(_connector(gateway), include_permissions=True)

    documents = {item.id: item for item in items if isinstance(item, Document)}
    thread = documents[thread_doc_id(CONVERSATION_ID)]
    assert len(thread.sections) == 3
    assert _readers(thread) == {"alice@contoso.com"}
    # Bob holds the newest message but not the private reply, Dave only the
    # private reply: each gets a document of his own copy.
    bob = documents[copy_document_id(thread.id.split(":", 1)[1], BOB)]
    assert len(bob.sections) == 2
    assert _readers(bob) == {"bob@contoso.com"}
    dave = documents[copy_document_id(thread.id.split(":", 1)[1], DAVE)]
    assert len(dave.sections) == 1
    assert _readers(dave) == {"dave@contoso.com"}
    assert set(documents) == {thread.id, bob.id, dave.id}
    # Alice and Bob were compared on their outlines. Dave was never a candidate.
    assert sorted(
        c.kwargs["mailbox_id"]
        for c in gateway.fetch_conversation_outline_page.call_args_list
    ) == [ALICE.id, BOB.id]


def test_a_listing_from_the_beginning_compares_copies_without_reading_outlines() -> (
    None
):
    """A window that opens at the beginning lists every message of each copy,
    so the copies are compared on the listing and no outline is fetched."""
    gateway = _private_reply_gateway()
    connector = _connector(gateway)

    with_outlines = {
        item.id: _readers(item)
        for item in _run(connector, include_permissions=True)
        if isinstance(item, Document)
    }
    outline_calls = gateway.fetch_conversation_outline_page.call_count
    assert outline_calls > 0

    documents = {
        item.id: _readers(item)
        for item in _run(connector, include_permissions=True, start=0)
        if isinstance(item, Document)
    }

    assert gateway.fetch_conversation_outline_page.call_count == outline_calls
    assert documents == with_outlines


def test_listing_covers_the_history_from_the_beginning_or_from_before_the_cutoff() -> (
    None
):
    unbounded = _connector(_happy_gateway())
    assert unbounded._listing_covers_history(0)
    assert not unbounded._listing_covers_history(START)

    bounded = _connector(_happy_gateway(), mail_history_days=30)
    now = datetime.now(timezone.utc)
    assert bounded._listing_covers_history(int((now - timedelta(days=45)).timestamp()))
    assert not bounded._listing_covers_history(
        int((now - timedelta(days=5)).timestamp())
    )


def test_slim_walk_yields_the_documents_indexing_builds_with_the_same_readers() -> None:
    gateway = _private_reply_gateway()
    connector = _connector(gateway)

    indexed = {
        item.id: _readers(item)
        for item in _run(connector, include_permissions=True)
        if isinstance(item, Document)
    }
    slim = {
        item.id: _readers(item)
        for batch in connector.retrieve_all_slim_docs_perm_sync()
        for item in batch
        if isinstance(item, SlimDocument)
    }

    assert slim == indexed
    assert len(indexed) == 3


def test_long_thread_copies_are_compared_on_the_same_window_in_both_walks() -> None:
    """Bob holds the most messages in all, Alice holds a private reply among
    the newest. Compared on everything, Bob builds and Alice reads his copy.
    Compared on the newest CONVERSATION_FETCH_LIMIT, the copies tie, Alice
    builds, and Bob must not read the private reply. Both walks must agree."""
    newest = RECEIVED + timedelta(days=2)
    shared = [
        message(id=f"m-{i}", received_at=RECEIVED + timedelta(minutes=i))
        for i in range(CONVERSATION_FETCH_LIMIT + 100)
    ]
    older = [
        message(id=f"old-{i}", received_at=RECEIVED - timedelta(days=1, minutes=i))
        for i in range(50)
    ]
    private = message(id="private", received_at=newest - timedelta(minutes=1))
    last = message(id="last", received_at=newest)
    held: dict[str, list[OutlookMessage]] = {
        ALICE.id: [last, private] + shared[::-1],
        BOB.id: [last] + shared[::-1] + older,
    }
    gateway = _happy_gateway()
    gateway.list_mailbox_users.return_value = OutlookMailboxPage(mailboxes=[ALICE, BOB])

    def delta(*, mailbox_id: str, folder_id: str, **_: Any) -> OutlookDeltaPage:
        if folder_id != INBOX_ID:
            return OutlookDeltaPage(changes=[])
        return OutlookDeltaPage(
            changes=[
                change(id=m.id, received_at=m.received_at) for m in held[mailbox_id]
            ]
        )

    def pages(items: list[Any], next_link: str | None) -> tuple[list[Any], str | None]:
        start = int(next_link.rsplit("=", 1)[1]) if next_link else 0
        chunk = items[start : start + 100]
        link = (
            f"https://graph/messages?skip={start + 100}"
            if start + 100 < len(items)
            else None
        )
        return chunk, link

    def messages(
        *, mailbox_id: str, next_link: str | None = None, **_: Any
    ) -> OutlookMessagePage:
        chunk, link = pages(held[mailbox_id], next_link)
        return OutlookMessagePage(messages=chunk, next_link=link)

    def outline(
        *, mailbox_id: str, next_link: str | None = None, **_: Any
    ) -> OutlookDeltaPage:
        chunk, link = pages(held[mailbox_id], next_link)
        return OutlookDeltaPage(
            changes=[change(id=m.id, received_at=m.received_at) for m in chunk],
            next_link=link,
        )

    gateway.fetch_folder_delta_page.side_effect = delta
    gateway.fetch_conversation_messages_page.side_effect = messages
    gateway.fetch_conversation_outline_page.side_effect = outline
    connector = _connector(gateway)

    indexed = {
        item.id: _readers(item)
        for item in _run(connector, include_permissions=True)
        if isinstance(item, Document)
    }
    slim = {
        item.id: _readers(item)
        for batch in connector.retrieve_all_slim_docs_perm_sync()
        for item in batch
        if isinstance(item, SlimDocument)
    }

    thread_id = thread_doc_id(CONVERSATION_ID)
    assert indexed[thread_id] == {"alice@contoso.com"}
    assert indexed == slim
    assert set(indexed) == {
        thread_id,
        copy_document_id(thread_id.split(":", 1)[1], BOB),
    }


def _paged(items: list[Any], next_link: str | None) -> tuple[list[Any], str | None]:
    start = int(next_link.rsplit("=", 1)[1]) if next_link else 0
    end = start + 100
    return items[start:end], (
        f"https://graph/messages?skip={end}" if end < len(items) else None
    )


def _two_copy_gateway(held: dict[str, list[OutlookMessage]]) -> MagicMock:
    """Alice and Bob each hold the given messages, paged by 100 for the
    listing, the outline and the bodies."""
    gateway = _happy_gateway()
    gateway.list_mailbox_users.return_value = OutlookMailboxPage(mailboxes=[ALICE, BOB])

    def delta(*, mailbox_id: str, folder_id: str, **_: Any) -> OutlookDeltaPage:
        if folder_id != INBOX_ID:
            return OutlookDeltaPage(changes=[])
        return OutlookDeltaPage(
            changes=[
                change(
                    id=m.id,
                    received_at=m.received_at,
                    parent_folder_id=m.parent_folder_id,
                )
                for m in held[mailbox_id]
                if m.parent_folder_id == INBOX_ID
            ]
        )

    def messages(
        *, mailbox_id: str, next_link: str | None = None, **_: Any
    ) -> OutlookMessagePage:
        chunk, link = _paged(held[mailbox_id], next_link)
        return OutlookMessagePage(messages=chunk, next_link=link)

    def outline(
        *, mailbox_id: str, next_link: str | None = None, **_: Any
    ) -> OutlookDeltaPage:
        chunk, link = _paged(held[mailbox_id], next_link)
        return OutlookDeltaPage(
            changes=[
                change(
                    id=m.id,
                    received_at=m.received_at,
                    parent_folder_id=m.parent_folder_id,
                )
                for m in chunk
            ],
            next_link=link,
        )

    gateway.fetch_folder_delta_page.side_effect = delta
    gateway.fetch_conversation_messages_page.side_effect = messages
    gateway.fetch_conversation_outline_page.side_effect = outline
    return gateway


def test_shared_messages_buried_under_trashed_ones_still_reach_the_document() -> None:
    """Bob's copy is the larger one but its newest 499 messages sit in Deleted
    Items. The bodies are read over the same pages as the outline, so the
    document still holds every shared message."""
    newest = RECEIVED + timedelta(days=2)
    shared = [
        message(id=f"m-{i}", received_at=RECEIVED + timedelta(minutes=i))
        for i in range(100)
    ]
    older = [
        message(id=f"old-{i}", received_at=RECEIVED - timedelta(days=1, minutes=i))
        for i in range(100)
    ]
    trashed = [
        message(
            id=f"trash-{i}",
            parent_folder_id=DELETED_ID,
            received_at=newest - timedelta(minutes=i),
        )
        for i in range(CONVERSATION_FETCH_LIMIT - 1)
    ]
    gateway = _two_copy_gateway(
        {ALICE.id: shared[::-1], BOB.id: trashed + shared[::-1] + older}
    )
    connector = _connector(gateway)

    documents = {
        item.id: item
        for item in _run(connector, include_permissions=True)
        if isinstance(item, Document)
    }

    thread = documents[thread_doc_id(CONVERSATION_ID)]
    assert len(thread.sections) == MAX_MESSAGES_PER_CONVERSATION
    assert thread.metadata["mailbox"] == BOB.address
    assert _readers(thread) == {ALICE.address, BOB.address}
    assert set(documents) == {thread.id}


def test_outline_stops_paging_once_a_page_is_older_than_the_history_cutoff() -> None:
    """Pages arrive newest first, so a page that ends before the cutoff means
    nothing older can matter. 150 recent messages end in the second page,
    which closes with ancient ones, so the last three pages are never read."""
    now = datetime.now(timezone.utc)
    recent = [
        message(id=f"m-{i}", received_at=now - timedelta(hours=i)) for i in range(150)
    ]
    ancient = [
        message(id=f"a-{i}", received_at=now - timedelta(days=400 + i))
        for i in range(300)
    ]
    gateway = _two_copy_gateway({ALICE.id: recent + ancient, BOB.id: recent + ancient})
    connector = _connector(gateway, mail_history_days=30)

    checkpoint = connector.build_dummy_checkpoint()
    generator = connector.load_from_checkpoint(
        int((now - timedelta(days=2)).timestamp()), int(now.timestamp()), checkpoint
    )
    for _ in range(50):
        try:
            next(generator)
        except StopIteration as stop:
            checkpoint = stop.value
            if not checkpoint.has_more:
                break
            generator = connector.load_from_checkpoint(
                int((now - timedelta(days=2)).timestamp()),
                int(now.timestamp()),
                checkpoint,
            )

    outline_pages = [
        c.kwargs.get("next_link")
        for c in gateway.fetch_conversation_outline_page.call_args_list
        if c.kwargs["mailbox_id"] == ALICE.id
    ]
    assert outline_pages == [None, "https://graph/messages?skip=100"]


def test_failure_in_one_mailbox_leaves_the_whole_step_to_be_retried() -> None:
    gateway = _many_mailbox_gateway(2)

    def probe(*, mailbox_id: str) -> OutlookFolder:
        if mailbox_id == "user-1":
            raise graph_error(503, "ServiceUnavailable")
        return folder()

    gateway.probe_mailbox.side_effect = probe
    connector = _connector(gateway)
    _, checkpoint = _step(connector, connector.build_dummy_checkpoint())

    with pytest.raises(OutlookGraphError):
        _step(connector, checkpoint)

    assert checkpoint.active == []
    assert checkpoint.mailboxes is not None and len(checkpoint.mailboxes) == 2


def test_failure_in_an_opened_mailbox_keeps_its_siblings_progress_out_of_the_checkpoint() -> (
    None
):
    gateway = _many_mailbox_gateway(2)
    connector = _connector(gateway)
    _, checkpoint = _step(connector, connector.build_dummy_checkpoint())
    _, checkpoint = _step(connector, checkpoint)
    assert [cursor.opened for cursor in checkpoint.active] == [True, True]
    before = checkpoint.model_copy(deep=True)

    def delta(*, mailbox_id: str, **_: object) -> OutlookDeltaPage:
        if mailbox_id == "user-1":
            raise graph_error(503, "ServiceUnavailable")
        return OutlookDeltaPage(changes=[change()])

    gateway.fetch_folder_delta_page.side_effect = delta
    escaped: list[object] = []
    generator = connector.load_from_checkpoint(START, END, checkpoint)
    with pytest.raises(OutlookGraphError):
        while True:
            escaped.append(next(generator))

    assert escaped == []
    assert checkpoint == before


def test_finished_mailbox_leaves_the_step_while_its_siblings_stay_active() -> None:
    gateway = _many_mailbox_gateway(2)

    def probe(*, mailbox_id: str) -> OutlookFolder:
        if mailbox_id == "user-1":
            raise graph_error(404, "MailboxNotEnabledForRESTAPI")
        return folder()

    gateway.probe_mailbox.side_effect = probe
    connector = _connector(gateway)
    _, checkpoint = _step(connector, connector.build_dummy_checkpoint())

    _, checkpoint = _step(connector, checkpoint)

    assert [cursor.mailbox.id for cursor in checkpoint.active] == ["user-0"]


def test_checkpoint_saved_before_any_mailbox_opened_loads_unchanged() -> None:
    saved = {
        "has_more": True,
        "mailboxes": [mailbox().model_dump()],
        "current_mailbox": None,
        "folders": None,
        "current_folder": None,
    }

    checkpoint = OutlookCheckpoint.model_validate_json(json.dumps(saved))

    assert checkpoint.mailboxes == [mailbox()]
    assert checkpoint.active == []


def test_checkpoint_saved_with_one_current_mailbox_resumes_where_it_stopped() -> None:
    saved = {
        "has_more": True,
        "mailboxes": [mailbox(id="user-2").model_dump()],
        "current_mailbox": mailbox().model_dump(),
        "folders": [folder(id=ARCHIVE_ID).model_dump()],
        "excluded_folder_ids": [JUNK_ID],
        "current_folder": folder().model_dump(),
        "delta_next_link": "https://graph/delta?more",
        "folder_change_count": 7,
        "calendar_done": True,
    }

    checkpoint = OutlookCheckpoint.model_validate_json(json.dumps(saved))

    assert checkpoint.mailboxes == [mailbox(id="user-2")]
    assert len(checkpoint.active) == 1
    cursor = checkpoint.active[0]
    assert cursor.mailbox == mailbox()
    assert cursor.opened
    assert cursor.folders == [folder(id=ARCHIVE_ID)]
    assert cursor.excluded_folder_ids == [JUNK_ID]
    assert cursor.current_folder == folder()
    assert cursor.delta_next_link == "https://graph/delta?more"
    assert cursor.folder_change_count == 7
    assert cursor.calendar_done


def test_oversized_single_mailbox_checkpoint_keeps_the_newest_within_the_cap() -> None:
    series: list[str] = [f"s-{i}" for i in range(MAX_TRACKED_SERIES_PER_MAILBOX + 2)]
    saved = {
        "has_more": True,
        "current_mailbox": mailbox().model_dump(),
        "seen_conversation_ids": {CONVERSATION_ID: None},
        "seen_series_ids": series,
    }

    cursor = OutlookCheckpoint.model_validate_json(json.dumps(saved)).active[0]

    assert cursor.seen_series_ids == set(series[2:])


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
    assert checkpoint.active == []


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


def test_thread_listed_several_times_on_a_page_is_built_once() -> None:
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

    _finish(connector, _folder_checkpoint())

    built = [
        c.kwargs["conversation_id"]
        for c in gateway.fetch_conversation_messages_page.call_args_list
    ]
    assert sorted(built) == sorted([CONVERSATION_ID, "conv-b"])


def test_conversations_of_a_page_are_yielded_in_page_order() -> None:
    """Rebuilds run side by side, so the first thread finishing last must not
    reorder the documents."""
    gateway = _happy_gateway()
    gateway.fetch_folder_delta_page.side_effect = None
    gateway.fetch_folder_delta_page.return_value = OutlookDeltaPage(
        changes=[change(), change(id="msg-b", conversation_id="conv-b")]
    )
    first_may_finish = threading.Event()

    def messages(*, conversation_id: str, **_: Any) -> OutlookMessagePage:
        if conversation_id == CONVERSATION_ID:
            assert first_may_finish.wait(timeout=5)
        else:
            first_may_finish.set()
        return OutlookMessagePage(messages=[message()])

    gateway.fetch_conversation_messages_page.side_effect = messages
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])

    items = _finish(connector, _folder_checkpoint())

    assert [item.id for item in items if isinstance(item, Document)] == [
        thread_doc_id(CONVERSATION_ID),
        thread_doc_id("conv-b"),
    ]


def test_failure_part_way_through_a_shard_leaves_the_shard_to_be_rebuilt() -> None:
    gateway = _happy_gateway()
    gateway.fetch_folder_delta_page.side_effect = None
    gateway.fetch_folder_delta_page.return_value = OutlookDeltaPage(
        changes=[change(), change(id="msg-b", conversation_id="conv-b")]
    )
    gateway.fetch_conversation_messages_page.side_effect = [
        OutlookMessagePage(messages=[message()]),
        OutlookAuthError("invalid_client", "secret expired"),
    ]
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])
    checkpoint = _folder_checkpoint()

    with pytest.raises(OutlookAuthError):
        _finish(connector, checkpoint)

    assert checkpoint.active == []
    assert checkpoint.build_buckets == 1
    assert checkpoint.next_bucket == 0 and checkpoint.next_thread == 0


def test_throttling_past_the_retries_fails_the_attempt_in_plain_words() -> None:
    gateway = _happy_gateway()
    gateway.fetch_folder_delta_page.side_effect = graph_error(429, "TooManyRequests")
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])
    checkpoint = _folder_checkpoint()

    with pytest.raises(RateLimitTriedTooManyTimesError) as exc_info:
        _step(connector, checkpoint)

    assert str(exc_info.value) == THROTTLED_MESSAGE
    assert isinstance(exc_info.value.__cause__, OutlookGraphError)
    assert checkpoint.active[0].current_folder == folder()


def test_expired_delta_state_restarts_the_folder_round() -> None:
    gateway = _happy_gateway()
    gateway.fetch_folder_delta_page.side_effect = graph_error(410, "SyncStateNotFound")
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])
    checkpoint = _folder_checkpoint(
        delta_next_link="https://graph/delta?$skiptoken=old", folder_change_count=7
    )

    items, checkpoint = _step(connector, checkpoint)

    assert items == []
    assert checkpoint.active[0].current_folder == folder()
    assert checkpoint.active[0].delta_next_link is None
    assert checkpoint.active[0].folder_change_count == 0


def test_vanished_folder_is_skipped() -> None:
    gateway = _happy_gateway()
    gateway.fetch_folder_delta_page.side_effect = graph_error(404, "ErrorItemNotFound")
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])

    items, checkpoint = _step(connector, _folder_checkpoint())

    assert items == []
    assert checkpoint.active[0].current_folder is None
    assert checkpoint.active[0].mailbox == mailbox()


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
    assert checkpoint.active[0].current_folder == folder()
    assert checkpoint.active[0].folder_unfiltered is True

    items, checkpoint = _step(connector, checkpoint)
    assert items == []
    assert checkpoint.active[0].current_folder is None
    assert windows == [datetime.fromtimestamp(START, tz=timezone.utc), None]
    assert checkpoint.listing_pages == 1


def test_conversation_fetch_refusal_is_a_document_failure() -> None:
    gateway = _happy_gateway()
    gateway.fetch_conversation_messages_page.side_effect = graph_error(
        404, "ErrorItemNotFound"
    )

    items = _run(_connector(gateway, mailboxes=[MAILBOX_ADDRESS]))

    failures = [item for item in items if isinstance(item, ConnectorFailure)]
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == thread_doc_id(CONVERSATION_ID)


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

    expected = RateLimitTriedTooManyTimesError if status == 429 else OutlookGraphError
    with pytest.raises(expected):
        _finish(connector, checkpoint)

    assert checkpoint.build_buckets == 1
    assert checkpoint.next_bucket == 0 and checkpoint.next_thread == 0


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

    doc = _build(messages)

    assert doc is not None
    assert len(doc.sections) == MAX_MESSAGES_PER_CONVERSATION
    assert doc.doc_updated_at == messages[-1].received_at
    assert doc.doc_created_at == messages[5].received_at


def test_conversation_without_messages_is_dropped() -> None:
    assert _build([]) is None


def test_conversation_without_a_subject_gets_a_placeholder_and_root_parent() -> None:
    doc = _build(
        [message(subject=None, parent_folder_id=None, sender=None, to_recipients=[])]
    )

    assert doc is not None
    assert doc.semantic_identifier == "(no subject)"
    assert doc.parent_hierarchy_raw_node_id == mailbox_node_id(mailbox())
    assert doc.primary_owners == []


def test_senders_are_not_repeated_as_secondary_owners() -> None:
    bob = OutlookRecipient(address="bob@contoso.com", name="Bob")
    alice = OutlookRecipient(address=MAILBOX_ADDRESS, name="Alice")
    doc = _build(
        [
            message(sender=alice, to_recipients=[bob]),
            message(id="msg-2", sender=bob, to_recipients=[alice]),
        ]
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
        items = _finish(connector, _folder_checkpoint())

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

    items = _finish(connector, _folder_checkpoint())

    assert len([item for item in items if isinstance(item, Document)]) == 1
    gateway.list_message_attachments.assert_not_called()


def test_attachment_over_the_cap_or_refused_is_skipped() -> None:
    gateway = _attachment_gateway()
    gateway.download_attachment.side_effect = SizeCapExceeded("during_download")
    connector = _attachment_connector(gateway)

    items = _finish(connector, _folder_checkpoint())
    docs = [item for item in items if isinstance(item, Document)]
    assert len(docs[0].sections) == 2

    gateway.download_attachment.side_effect = graph_error(404, "ErrorItemNotFound")
    items = _finish(connector, _folder_checkpoint())
    docs = [item for item in items if isinstance(item, Document)]
    assert len(docs[0].sections) == 2


def test_throttled_attachment_read_keeps_the_checkpoint() -> None:
    gateway = _attachment_gateway()
    gateway.download_attachment.side_effect = graph_error(429, "TooManyRequests")
    connector = _attachment_connector(gateway)
    checkpoint = _folder_checkpoint()

    with pytest.raises(RateLimitTriedTooManyTimesError):
        _finish(connector, checkpoint)

    assert checkpoint.next_bucket == 0 and checkpoint.next_thread == 0


def test_refused_attachment_listing_keeps_the_message_text() -> None:
    gateway = _attachment_gateway()
    gateway.list_message_attachments.side_effect = graph_error(403)
    connector = _attachment_connector(gateway)

    items = _finish(connector, _folder_checkpoint())

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
        items = _finish(connector, _folder_checkpoint())

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
        items = _finish(connector, _folder_checkpoint())

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
        items = _finish(connector, _folder_checkpoint())

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
        thread_doc_id(cid) for cid in (CONVERSATION_ID, "conv-late", "conv-old")
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

    # Three walked folders of 501 threads each, listed per folder and
    # batched once every mailbox is read, with one report for the bucket.
    slim_batches = [b for b in batches if isinstance(b[0], SlimDocument)]
    assert [len(b) for b in slim_batches] == [SLIM_BATCH_SIZE] * 3 + [3]
    # The zero is the heartbeat of the cut into buckets.
    assert callback.progress.call_args_list == [
        call("outlook_slim_docs", SLIM_BATCH_SIZE + 1)
    ] * 3 + [
        call("outlook_slim_docs", 0),
        call("outlook_slim_docs", 3 * SLIM_BATCH_SIZE + 3),
    ]


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
        thread_doc_id(CONVERSATION_ID),
        thread_doc_id("conv-2"),
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
        event_document_id(mailbox(), "evt-1"),
        event_document_id(mailbox(), SERIES_ID),
        event_document_id(mailbox(), "exc-1"),
        thread_doc_id(CONVERSATION_ID),
    ]
    # Two occurrences, one master read, one document carrying the pattern.
    gateway.get_event.assert_called_once_with(
        mailbox_id=mailbox().id, event_id=SERIES_ID
    )
    series = docs[1]
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
    assert checkpoint.active[0].calendar_next_link is None
    assert checkpoint.active[0].calendar_done is False
    assert checkpoint.active[0].mailbox == mailbox()


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
        thread_doc_id(CONVERSATION_ID)
    ]

    every = _run(_connector(gateway, include_calendar=True))
    assert not [item for item in every if isinstance(item, ConnectorFailure)]


def test_throttled_calendar_read_keeps_the_checkpoint() -> None:
    gateway = _calendar_gateway()
    gateway.fetch_calendar_delta_page.side_effect = graph_error(429, "TooManyRequests")
    connector = _calendar_connector(gateway)
    checkpoint = _folder_checkpoint(current_folder=None)

    with pytest.raises(RateLimitTriedTooManyTimesError):
        _step(connector, checkpoint)

    assert checkpoint.active[0].calendar_done is False


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

    assert checkpoint.active[0].calendar_done is False
    assert checkpoint.active[0].seen_series_ids == set()


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

    assert thread_doc_id(CONVERSATION_ID) in ids
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
    # The holders, whether indexing or the permission sync wrote it.
    assert _readers(by_id[thread_doc_id(CONVERSATION_ID)]) == {MAILBOX_ADDRESS}
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
