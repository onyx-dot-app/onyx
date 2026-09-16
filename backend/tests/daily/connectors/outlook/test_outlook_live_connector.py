"""Live checks of the Outlook connector against the shared Microsoft test tenant.

The SharePoint test app also holds Mail.Read, Calendars.Read and User.Read.All,
so its secret serves here. One mailbox holds the fixtures: unchanging Sent
Items, an inbox that keeps receiving notifications, and one meeting."""

import os
import re
import time
from datetime import datetime, timezone

import pytest

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.models import (
    BasicExpertInfo,
    Document,
    HierarchyNode,
    SlimDocument,
)
from onyx.connectors.outlook.connector import (
    CALENDAR_NODE_PREFIX,
    DOCUMENT_ID_PREFIX,
    EVENT_DOCUMENT_ID_PREFIX,
    MAILBOX_NODE_PREFIX,
    OutlookConnector,
)
from onyx.db.enums import HierarchyNodeType
from tests.daily.connectors.utils import ConnectorOutput, load_all_from_connector
from tests.utils.pytest_secrets import RedactedDict
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(TestSecret.SHAREPOINT_CLIENT_SECRET)

TEST_MAILBOX = "test@danswerai.onmicrosoft.com"
# No tenant user has this address, so validation must refuse it every run.
MISSING_MAILBOX = "missing-mailbox-for-onyx-tests@danswerai.onmicrosoft.com"

# Graph stamps sent mail with a receivedDateTime too. Sent Items never change
# and new mail cannot land in a past window, so this range holds one conversation.
FOLDER_SHARE_SUBJECT = 'Test User shared the folder "test folder" with you'
FOLDER_SHARE_RECIPIENT = "subash@onyx.app"
FOLDER_SHARE_WINDOW_START = datetime(2026, 8, 6, 17, 6, tzinfo=timezone.utc)
FOLDER_SHARE_WINDOW_END = datetime(2026, 8, 6, 17, 8, tzinfo=timezone.utc)

# The one meeting in the calendar, organized from the test mailbox.
EVENT_SUBJECT = "Test event"
EVENT_START = "2026-09-16T02:00"
EVENT_ATTENDEES = {"evan@onyx.app", "subash@onyx.app"}
# Keeps the meeting inside the calendar window for years either way.
CALENDAR_WINDOW_DAYS = 3650

OWNER_ACCESS = ExternalAccess(
    external_user_emails={TEST_MAILBOX},
    external_user_group_ids=set(),
    is_public=False,
)
EVENT_ACCESS = ExternalAccess(
    external_user_emails={TEST_MAILBOX, *EVENT_ATTENDEES},
    external_user_group_ids=set(),
    is_public=False,
)


@pytest.fixture
def outlook_credentials(
    test_secrets: dict[TestSecret, str],
) -> RedactedDict[str, str]:
    return RedactedDict(
        {
            "outlook_client_id": os.environ["SHAREPOINT_CLIENT_ID"],
            "outlook_client_secret": test_secrets[TestSecret.SHAREPOINT_CLIENT_SECRET],
            "outlook_directory_id": os.environ["SHAREPOINT_CLIENT_DIRECTORY_ID"],
        }
    )


def _connector(
    credentials: dict[str, str],
    include_calendar: bool = False,
    mailboxes: list[str] | None = None,
) -> OutlookConnector:
    connector = OutlookConnector(
        mailboxes=mailboxes or [TEST_MAILBOX],
        include_calendar=include_calendar,
        calendar_past_days=CALENDAR_WINDOW_DAYS,
        calendar_future_days=CALENDAR_WINDOW_DAYS,
    )
    connector.load_credentials(credentials)
    return connector


def _emails(experts: list[BasicExpertInfo] | None) -> set[str]:
    return {expert.email.lower() for expert in experts or [] if expert.email}


def _conversation_sent_by_mailbox(documents: list[Document], subject: str) -> Document:
    # The inbox may gain a notification with the same subject, so the sender
    # narrows the match to the fixture.
    matches = [
        d
        for d in documents
        if d.id.startswith(DOCUMENT_ID_PREFIX)
        and d.semantic_identifier == subject
        and TEST_MAILBOX in _emails(d.primary_owners)
    ]
    assert len(matches) == 1, (
        f"Expected one conversation titled {subject!r} sent by the mailbox, "
        f"found {len(matches)}"
    )
    return matches[0]


def _mailbox_node(nodes: list[HierarchyNode]) -> HierarchyNode:
    mailbox_nodes = [n for n in nodes if n.node_type == HierarchyNodeType.MAILBOX]
    assert len(mailbox_nodes) == 1, f"Expected one mailbox node, got {mailbox_nodes}"
    node = mailbox_nodes[0]
    assert node.raw_node_id.startswith(MAILBOX_NODE_PREFIX)
    assert node.raw_parent_id is None
    return node


def _calendar_nodes(nodes: list[HierarchyNode]) -> list[HierarchyNode]:
    return [n for n in nodes if n.raw_node_id.startswith(CALENDAR_NODE_PREFIX)]


def _folder_names(nodes: list[HierarchyNode], parent_id: str) -> set[str]:
    return {
        n.display_name
        for n in nodes
        if n.node_type == HierarchyNodeType.FOLDER and n.raw_parent_id == parent_id
    }


def _assert_plain_walk(result: ConnectorOutput) -> None:
    """A walk without permission sync carries no readership anywhere."""
    assert result.documents, "The test mailbox holds mail, so the walk must yield"
    for node in result.hierarchy_nodes:
        assert node.external_access is None, node.display_name
    node_ids = {n.raw_node_id for n in result.hierarchy_nodes}
    for doc in result.documents:
        assert doc.source == DocumentSource.OUTLOOK
        assert doc.metadata["mailbox"] == TEST_MAILBOX
        assert doc.parent_hierarchy_raw_node_id in node_ids
        assert doc.external_access is None, doc.semantic_identifier
        assert doc.sections, doc.semantic_identifier
        for section in doc.sections:
            assert section.text and section.link, doc.semantic_identifier


def _expected_access(doc: Document) -> ExternalAccess:
    if doc.id.startswith(EVENT_DOCUMENT_ID_PREFIX):
        return EVENT_ACCESS
    return OWNER_ACCESS


def test_mailbox_walk_yields_conversations_under_their_folders(
    outlook_credentials: dict[str, str],
) -> None:
    result = load_all_from_connector(
        connector=_connector(outlook_credentials), start=0, end=time.time()
    )
    _assert_plain_walk(result)

    mailbox_node = _mailbox_node(result.hierarchy_nodes)
    folder_names = _folder_names(result.hierarchy_nodes, mailbox_node.raw_node_id)
    assert {"Inbox", "Sent Items"} <= folder_names, folder_names
    assert not {"Junk Email", "Deleted Items"} & folder_names, folder_names
    assert not _calendar_nodes(result.hierarchy_nodes), "Calendar is off"
    for doc in result.documents:
        assert doc.id.startswith(DOCUMENT_ID_PREFIX), doc.id

    share = _conversation_sent_by_mailbox(result.documents, FOLDER_SHARE_SUBJECT)
    assert share.metadata["message_count"] == "1"
    assert _emails(share.primary_owners) == {TEST_MAILBOX}
    assert _emails(share.secondary_owners) == {FOLDER_SHARE_RECIPIENT}
    text = share.sections[0].text
    assert text is not None
    assert text.startswith("From: ") and "To: " in text, text[:200]
    assert isinstance(share.doc_updated_at, datetime)
    assert share.doc_updated_at.tzinfo == timezone.utc


def test_poll_window_returns_only_the_conversation_that_changed(
    outlook_credentials: dict[str, str],
) -> None:
    result = load_all_from_connector(
        connector=_connector(outlook_credentials),
        start=FOLDER_SHARE_WINDOW_START.timestamp(),
        end=FOLDER_SHARE_WINDOW_END.timestamp(),
    )

    assert [d.semantic_identifier for d in result.documents] == [FOLDER_SHARE_SUBJECT]


def test_calendar_walk_yields_the_meeting_under_the_calendar_node(
    outlook_credentials: dict[str, str],
) -> None:
    result = load_all_from_connector(
        connector=_connector(outlook_credentials, include_calendar=True),
        start=0,
        end=time.time(),
    )
    _assert_plain_walk(result)

    mailbox_node = _mailbox_node(result.hierarchy_nodes)
    calendar_nodes = _calendar_nodes(result.hierarchy_nodes)
    assert len(calendar_nodes) == 1, calendar_nodes
    assert calendar_nodes[0].display_name == "Calendar"
    assert calendar_nodes[0].raw_parent_id == mailbox_node.raw_node_id

    events = [d for d in result.documents if d.id.startswith(EVENT_DOCUMENT_ID_PREFIX)]
    assert len(events) == 1, [e.semantic_identifier for e in events]
    event = events[0]
    assert event.semantic_identifier == EVENT_SUBJECT
    assert event.parent_hierarchy_raw_node_id == calendar_nodes[0].raw_node_id
    assert event.metadata["recurring"] == "false"
    start = event.metadata["start"]
    assert isinstance(start, str) and start.startswith(EVENT_START), event.metadata
    assert _emails(event.primary_owners) == {TEST_MAILBOX}
    assert _emails(event.secondary_owners) == EVENT_ATTENDEES
    text = event.sections[0].text
    assert text is not None
    assert "Organizer: " in text and TEST_MAILBOX in text, text
    for attendee in EVENT_ATTENDEES:
        assert attendee in text, text

    # The meeting request the organizer sent shares the event's subject, and
    # replies fold into it and turn an attendee into a sender.
    invitation = _conversation_sent_by_mailbox(result.documents, EVENT_SUBJECT)
    on_thread = _emails(invitation.primary_owners) | _emails(
        invitation.secondary_owners
    )
    assert EVENT_ATTENDEES <= on_thread, on_thread


def test_permission_sync_walks_attach_the_same_readers(
    outlook_credentials: dict[str, str],
) -> None:
    connector = _connector(outlook_credentials, include_calendar=True)
    result = load_all_from_connector(
        connector=connector, start=0, end=time.time(), include_permissions=True
    )

    for node in result.hierarchy_nodes:
        assert node.external_access == OWNER_ACCESS, node.display_name
    indexed_access: dict[str, ExternalAccess | None] = {}
    for doc in result.documents:
        assert doc.external_access == _expected_access(doc), doc.semantic_identifier
        indexed_access[doc.id] = doc.external_access
    assert [a for a in indexed_access.values() if a == EVENT_ACCESS] == [EVENT_ACCESS]
    assert OWNER_ACCESS in indexed_access.values(), "No conversation was indexed"

    listed_access: dict[str, ExternalAccess | None] = {}
    for batch in connector.retrieve_all_slim_docs_perm_sync():
        for entry in batch:
            if isinstance(entry, HierarchyNode):
                assert entry.external_access == OWNER_ACCESS, entry.display_name
                continue
            assert isinstance(entry, SlimDocument)
            listed_access[entry.id] = entry.external_access

    # The inbox keeps receiving mail, so the listing may hold conversations the
    # earlier walk had not seen, never fewer.
    missing = set(indexed_access) - set(listed_access)
    assert not missing, f"Pruning would drop indexed documents: {missing}"
    for doc_id, access in indexed_access.items():
        assert listed_access[doc_id] == access, doc_id


def test_settings_validation_names_a_missing_mailbox(
    outlook_credentials: dict[str, str],
) -> None:
    _connector(outlook_credentials).validate_connector_settings()

    connector = _connector(outlook_credentials, mailboxes=[MISSING_MAILBOX])
    with pytest.raises(ConnectorValidationError, match=re.escape(MISSING_MAILBOX)):
        connector.validate_connector_settings()
