"""The Outlook connector walk: mailboxes, folders, delta pages, conversations.

The gateway is autospecced, so these tests drive the real checkpoint state
machine and document assembly against the gateway's plain models.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, call, create_autospec

import pytest

from onyx.connectors.exceptions import ConnectorValidationError, CredentialInvalidError
from onyx.connectors.models import (
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    SlimDocument,
)
from onyx.connectors.outlook import connector as connector_module
from onyx.connectors.outlook.connector import (
    CONVERSATION_FETCH_LIMIT,
    FILTERED_DELTA_CAP,
    MAX_MESSAGES_PER_CONVERSATION,
    SLIM_BATCH_SIZE,
    OutlookCheckpoint,
    OutlookConnector,
    build_conversation_document,
    conversation_document_id,
    indexable_messages,
    mailbox_node_id,
)
from onyx.connectors.outlook.models import (
    OutlookAuthError,
    OutlookDeltaPage,
    OutlookFolder,
    OutlookFolderPage,
    OutlookGraphError,
    OutlookMailboxPage,
    OutlookMessagePage,
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
    graph_error,
    mailbox,
    message,
)

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


def test_validation_lists_unreachable_configured_mailboxes() -> None:
    gateway = _happy_gateway()
    gateway.resolve_mailbox.side_effect = [None, mailbox(id="user-2")]
    gateway.probe_mailbox.side_effect = graph_error(404, "MailboxNotEnabledForRESTAPI")

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
    with pytest.raises(ConnectorMissingCredentialError):
        _ = OutlookConnector().ops


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
