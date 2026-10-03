import copy
import datetime
import json
import os
from typing import Any, cast
from unittest.mock import MagicMock, patch

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.gmail.connector import (
    GmailCheckpoint,
    GmailConnector,
    _build_time_range_query,
    thread_to_document,
)
from onyx.connectors.models import Document, TextSection
from tests.unit.onyx.connectors.utils import (
    load_everything_from_checkpoint_connector_from_checkpoint,
)


def test_thread_to_document() -> None:
    json_path = os.path.join(os.path.dirname(__file__), "thread.json")
    with open(json_path, "r") as f:
        full_email_thread = json.load(f)

    doc = thread_to_document(full_email_thread, "admin@onyx-test.com")
    assert isinstance(doc, Document)
    assert doc.source == DocumentSource.GMAIL
    assert doc.semantic_identifier == "Email Chain 1"
    assert doc.doc_updated_at == datetime.datetime(
        2024, 11, 2, 17, 34, 55, tzinfo=datetime.timezone.utc
    )
    assert len(doc.sections) == 4
    assert doc.metadata == {}


def test_build_time_range_query() -> None:
    time_range_start = 1703066296.159339
    time_range_end = 1704984791.657404
    query = _build_time_range_query(time_range_start, time_range_end)
    assert query == "after:1703066296 before:1704984791"
    query = _build_time_range_query(time_range_start, None)
    assert query == "after:1703066296"
    query = _build_time_range_query(None, time_range_end)
    assert query == "before:1704984791"
    query = _build_time_range_query(0.0, time_range_end)
    assert query == "before:1704984791"
    query = _build_time_range_query(None, None)
    assert query is None


def _thread_with_date(date_header: str | None) -> dict[str, Any]:
    """Load the fixture thread and replace (or strip, if None) its Date header."""
    json_path = os.path.join(os.path.dirname(__file__), "thread.json")
    with open(json_path, "r") as f:
        thread = cast(dict[str, Any], json.load(f))
    thread = copy.deepcopy(thread)

    for message in thread["messages"]:
        headers: list[dict[str, str]] = message["payload"]["headers"]
        if date_header is None:
            message["payload"]["headers"] = [
                h for h in headers if h.get("name") != "Date"
            ]
            continue

        replaced = False
        for header in headers:
            if header.get("name") == "Date":
                header["value"] = date_header
                replaced = True
                break
        if not replaced:
            headers.append({"name": "Date", "value": date_header})

    return thread


def test_thread_to_document_skips_unparseable_dates() -> None:
    for bad_date in (
        "Wed, 33 Sep 2007 13:42:59 +0100",
        "Thu, 11 Oct 2007 31:50:55 +0900",
        "total garbage not even close to a date",
    ):
        doc = thread_to_document(_thread_with_date(bad_date), "admin@example.com")
        assert isinstance(doc, Document), f"failed for {bad_date!r}"
        assert doc.doc_updated_at is None
        assert doc.id == "192edefb315737c3"


def test_thread_to_document_keeps_owner_names_across_messages() -> None:
    # In the fixture, the admin sends messages 1 and 3 and receives messages 2 and 4.
    json_path = os.path.join(os.path.dirname(__file__), "thread.json")
    with open(json_path, "r") as f:
        full_email_thread = json.load(f)

    doc = thread_to_document(full_email_thread, "admin@onyx-test.com")
    assert isinstance(doc, Document)

    senders = {o.email: o for o in doc.primary_owners or []}
    recipients = {o.email: o for o in doc.secondary_owners or []}
    for owners in (senders, recipients):
        admin = owners["admin@onyx-test.com"]
        assert (admin.first_name, admin.last_name) == ("Test Admin", "Admin")


def _thread_with_to_header(to_header: str) -> dict[str, Any]:
    json_path = os.path.join(os.path.dirname(__file__), "thread.json")
    with open(json_path, "r") as f:
        thread = cast(dict[str, Any], json.load(f))
    thread["messages"] = thread["messages"][:1]
    for header in thread["messages"][0]["payload"]["headers"]:
        if header.get("name") == "To":
            header["value"] = to_header
    return thread


def test_thread_to_document_keeps_every_recipient_in_a_header() -> None:
    thread = _thread_with_to_header(
        'Alice Smith <alice@example.com>, "Doe, Jane" <jane@example.com>, '
        "bob@example.com"
    )

    doc = thread_to_document(thread, "admin@onyx-test.com")
    assert isinstance(doc, Document)

    recipients = {o.email: o for o in doc.secondary_owners or []}
    assert set(recipients) == {
        "alice@example.com",
        "jane@example.com",
        "bob@example.com",
    }
    assert recipients["alice@example.com"].first_name == "Alice"
    assert recipients["alice@example.com"].last_name == "Smith"
    assert recipients["bob@example.com"].first_name is None


def test_gmail_checkpoint_progression() -> None:
    connector = GmailConnector()
    connector._creds = MagicMock()
    connector._primary_admin_email = "admin@example.com"

    user_emails = ["user1@example.com", "user2@example.com"]

    thread_list_responses: dict[str, dict[str | None, dict[str, Any]]] = {
        "user1@example.com": {
            None: {
                "threads": [{"id": "t1"}, {"id": "t2"}],
                "nextPageToken": "token-user1-page2",
            },
            "token-user1-page2": {
                "threads": [{"id": "t3"}],
                "nextPageToken": None,
            },
        },
        "user2@example.com": {
            None: {
                "threads": [{"id": "t4"}],
                "nextPageToken": None,
            }
        },
    }

    full_thread_responses = {
        "user1@example.com": {
            "t1": {"id": "t1"},
            "t2": {"id": "t2"},
            "t3": {"id": "t3"},
        },
        "user2@example.com": {
            "t4": {"id": "t4"},
        },
    }

    class MockRequest:
        def __init__(self, response: dict[str, Any]):
            self._response = response

        def execute(self) -> dict[str, Any]:
            return self._response

    class MockThreadsResource:
        def __init__(self, user_email: str) -> None:
            self._user_email = user_email

        def list(
            self,
            *,
            userId: str,
            fields: str,
            q: str | None = None,  # noqa: ARG002
            pageToken: str | None = None,
            **_: object,
        ) -> MockRequest:
            assert userId == self._user_email
            assert "nextPageToken" in fields
            responses = thread_list_responses[self._user_email]
            key = pageToken or None
            return MockRequest(responses[key])

        def get(
            self,
            *,
            userId: str,
            id: str,
            fields: str,
            **_: object,
        ) -> MockRequest:
            assert userId == self._user_email
            assert "messages" in fields or "payload" in fields
            return MockRequest(full_thread_responses[self._user_email][id])

    class MockUsersResource:
        def __init__(self, user_email: str) -> None:
            self._user_email = user_email

        def threads(self) -> MockThreadsResource:
            return MockThreadsResource(self._user_email)

    class MockGmailService:
        def __init__(self, user_email: str) -> None:
            self._user_email = user_email

        def users(self) -> MockUsersResource:
            return MockUsersResource(self._user_email)

    def fake_get_gmail_service(_: object, user_email: str) -> MockGmailService:
        return MockGmailService(user_email)

    def fake_thread_to_document(
        full_thread: dict[str, object], user_email: str
    ) -> Document:
        thread_id = cast(str, full_thread["id"])
        return Document(
            id=f"{user_email}:{thread_id}",
            semantic_identifier=f"Thread {thread_id}",
            sections=[TextSection(text=f"Body {thread_id}")],
            source=DocumentSource.GMAIL,
            metadata={},
            external_access=ExternalAccess(
                external_user_emails={user_email},
                external_user_group_ids=set(),
                is_public=False,
            ),
        )

    checkpoint = connector.build_dummy_checkpoint()
    assert isinstance(checkpoint, GmailCheckpoint)

    with patch.object(GmailConnector, "_get_all_user_emails", return_value=user_emails):
        with patch(
            "onyx.connectors.gmail.connector.get_gmail_service",
            side_effect=fake_get_gmail_service,
        ):
            with patch(
                "onyx.connectors.gmail.connector.thread_to_document",
                side_effect=fake_thread_to_document,
            ) as mock_thread_to_document:
                outputs = load_everything_from_checkpoint_connector_from_checkpoint(
                    connector=connector,
                    start=0,
                    end=1_000,
                    checkpoint=checkpoint,
                )

    document_ids = [
        item.id
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]

    assert document_ids == [
        "user2@example.com:t4",
        "user1@example.com:t1",
        "user1@example.com:t2",
        "user1@example.com:t3",
    ]

    assert mock_thread_to_document.call_count == 4

    final_checkpoint = outputs[-1].next_checkpoint
    assert isinstance(final_checkpoint, GmailCheckpoint)
    assert final_checkpoint.has_more is False
    assert final_checkpoint.user_emails == []
