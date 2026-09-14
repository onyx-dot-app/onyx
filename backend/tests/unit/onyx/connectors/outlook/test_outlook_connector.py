"""The Outlook connector walk: mailboxes, folders, delta pages, conversations.

The gateway is autospecced, so these tests drive the real checkpoint state
machine and document assembly against canned Graph shapes.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest

from onyx.connectors.exceptions import ConnectorValidationError, CredentialInvalidError
from onyx.connectors.models import ConnectorFailure, Document, HierarchyNode
from onyx.connectors.outlook.connector import (
    MAX_MESSAGES_PER_CONVERSATION,
    OutlookCheckpoint,
    OutlookConnector,
    build_conversation_document,
    conversation_document_id,
    mailbox_node_id,
)
from onyx.connectors.outlook.models import (
    OutlookAuthError,
    OutlookDeltaPage,
    OutlookFolder,
    OutlookFolderPage,
    OutlookGraphError,
    OutlookMailboxPage,
    OutlookRecipient,
)
from onyx.connectors.outlook.source_operations import OutlookSourceOperations
from onyx.db.enums import HierarchyNodeType
from tests.unit.onyx.connectors.outlook.outlook_api_shapes import (
    CONVERSATION_ID,
    INBOX_ID,
    MAILBOX_ADDRESS,
    RECEIVED,
    change,
    folder,
    mailbox,
    message,
)

JUNK_ID = "folder-junk"
DELETED_ID = "folder-deleted"
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
    if parent_folder_id is None:
        return OutlookFolderPage(
            folders=[
                folder(child_folder_count=1),
                folder(id=JUNK_ID, display_name="Junk Email"),
                folder(id=DELETED_ID, display_name="Deleted Items"),
                folder(id=SEARCH_ID, display_name="Digests", is_search_folder=True),
                folder(id=ARCHIVE_ID, display_name="Archive"),
            ]
        )
    if parent_folder_id == INBOX_ID:
        return OutlookFolderPage(
            folders=[
                folder(
                    id=PROJECTS_ID, display_name="Projects", parent_folder_id=INBOX_ID
                )
            ]
        )
    return OutlookFolderPage(folders=[])


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
            change(id="msg-gone", removed=True, conversation_id=None),
            change(id="msg-2"),
            change(
                id="msg-late",
                conversation_id="conv-late",
                received_at=RECEIVED + timedelta(days=2),
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
    gateway.list_conversation_messages.return_value = [
        message(id="msg-2", received_at=RECEIVED + timedelta(hours=1)),
        message(),
        message(id="msg-junk", parent_folder_id=JUNK_ID),
        message(id="msg-draft", is_draft=True),
    ]
    return gateway


def _step(
    connector: OutlookConnector, checkpoint: OutlookCheckpoint
) -> tuple[list[Document | HierarchyNode | ConnectorFailure], OutlookCheckpoint]:
    items: list[Document | HierarchyNode | ConnectorFailure] = []
    generator = connector.load_from_checkpoint(START, END, checkpoint)
    while True:
        try:
            items.append(next(generator))
        except StopIteration as stop:
            return items, stop.value


def _run(
    connector: OutlookConnector,
) -> list[Document | HierarchyNode | ConnectorFailure]:
    """Drive the walk to completion, round-tripping the checkpoint as JSON each
    step the way the indexing pipeline persists it."""
    checkpoint = connector.build_dummy_checkpoint()
    collected: list[Document | HierarchyNode | ConnectorFailure] = []
    for _ in range(50):
        items, checkpoint = _step(connector, checkpoint)
        collected.extend(items)
        checkpoint = connector.validate_checkpoint_json(checkpoint.model_dump_json())
        if not checkpoint.has_more:
            return collected
    raise AssertionError("walk did not finish in 50 steps")


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
    gateway.list_conversation_messages.assert_called_once()


def test_walk_skips_removed_late_and_repeated_changes() -> None:
    gateway = _happy_gateway()

    _run(_connector(gateway, mailboxes=[MAILBOX_ADDRESS]))

    conversations = [
        call.kwargs["conversation_id"]
        for call in gateway.list_conversation_messages.call_args_list
    ]
    assert conversations == [CONVERSATION_ID]


def test_walk_filters_delta_by_the_poll_window_start() -> None:
    gateway = _happy_gateway()

    _run(_connector(gateway, mailboxes=[MAILBOX_ADDRESS]))

    first_delta = gateway.fetch_folder_delta_page.call_args_list[0]
    assert first_delta.kwargs["received_after"] == datetime.fromtimestamp(
        START, tz=timezone.utc
    )


def test_walk_excludes_junk_deleted_and_search_folders_from_folders_walked() -> None:
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


def test_unresolved_configured_mailbox_is_a_recorded_failure() -> None:
    gateway = _happy_gateway()
    gateway.resolve_mailbox.return_value = None

    items = _run(_connector(gateway, mailboxes=["ghost@contoso.com"]))

    failures = [item for item in items if isinstance(item, ConnectorFailure)]
    assert len(failures) == 1
    assert failures[0].failed_entity is not None
    assert failures[0].failed_entity.entity_id == "ghost@contoso.com"


def test_denied_mailbox_is_a_failure_when_named_and_a_skip_otherwise() -> None:
    gateway = _happy_gateway()
    gateway.probe_mailbox.side_effect = OutlookGraphError(
        403, "ErrorAccessDenied", "denied"
    )

    named = _run(_connector(gateway, mailboxes=[MAILBOX_ADDRESS]))
    assert [type(item) for item in named] == [ConnectorFailure]

    gateway.probe_mailbox.side_effect = OutlookGraphError(
        403, "ErrorAccessDenied", "denied"
    )
    every = _run(_connector(gateway))
    assert every == []


def test_unexpected_probe_error_fails_the_run() -> None:
    gateway = _happy_gateway()
    gateway.probe_mailbox.side_effect = OutlookGraphError(
        500, "InternalServerError", "boom"
    )

    with pytest.raises(OutlookGraphError):
        _run(_connector(gateway, mailboxes=[MAILBOX_ADDRESS]))


def test_expired_delta_state_restarts_the_folder_round() -> None:
    gateway = _happy_gateway()
    gateway.fetch_folder_delta_page.side_effect = OutlookGraphError(
        410, "SyncStateNotFound", "gone"
    )
    connector = _connector(gateway, mailboxes=[MAILBOX_ADDRESS])
    checkpoint = OutlookCheckpoint(
        has_more=True,
        mailboxes=[],
        current_mailbox=mailbox(),
        folders=[],
        current_folder=folder(),
        delta_next_link="https://graph/delta?$skiptoken=old",
    )

    items, checkpoint = _step(connector, checkpoint)

    assert items == []
    assert checkpoint.current_folder == folder()
    assert checkpoint.delta_next_link is None


def test_conversation_fetch_failure_is_a_document_failure() -> None:
    gateway = _happy_gateway()
    gateway.list_conversation_messages.side_effect = OutlookGraphError(
        503, "ServiceUnavailable", "busy"
    )

    items = _run(_connector(gateway, mailboxes=[MAILBOX_ADDRESS]))

    failures = [item for item in items if isinstance(item, ConnectorFailure)]
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == conversation_document_id(
        mailbox(), CONVERSATION_ID
    )


def test_conversation_keeps_only_the_newest_messages() -> None:
    messages = [
        message(id=f"msg-{i}", received_at=RECEIVED + timedelta(minutes=i))
        for i in range(MAX_MESSAGES_PER_CONVERSATION + 5)
    ]

    doc = build_conversation_document(mailbox(), CONVERSATION_ID, messages, set())

    assert doc is not None
    assert len(doc.sections) == MAX_MESSAGES_PER_CONVERSATION
    assert doc.doc_updated_at == messages[-1].received_at
    assert doc.doc_created_at == messages[5].received_at


def test_conversation_without_indexable_messages_is_dropped() -> None:
    assert (
        build_conversation_document(
            mailbox(), CONVERSATION_ID, [message(is_draft=True)], set()
        )
        is None
    )


def test_conversation_without_a_subject_gets_a_placeholder_and_root_parent() -> None:
    doc = build_conversation_document(
        mailbox(),
        CONVERSATION_ID,
        [message(subject=None, parent_folder_id=None, sender=None, to_recipients=[])],
        set(),
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
        set(),
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


def test_validation_lists_unreachable_configured_mailboxes() -> None:
    gateway = _happy_gateway()
    gateway.resolve_mailbox.side_effect = [None, mailbox(id="user-2")]
    gateway.probe_mailbox.side_effect = OutlookGraphError(
        404, "MailboxNotEnabledForRESTAPI", "no"
    )

    with pytest.raises(ConnectorValidationError) as exc_info:
        _connector(
            gateway, mailboxes=["ghost@contoso.com", "unlicensed@contoso.com"]
        ).validate_connector_settings()

    assert "ghost@contoso.com (no such user)" in str(exc_info.value)
    assert "unlicensed@contoso.com (MailboxNotEnabledForRESTAPI)" in str(exc_info.value)


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
    with pytest.raises(RuntimeError):
        _ = OutlookConnector().ops
