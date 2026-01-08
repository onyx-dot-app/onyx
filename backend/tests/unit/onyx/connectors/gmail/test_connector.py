import datetime
import json
import os
from typing import Any
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.gmail.connector import _build_time_range_query
from onyx.connectors.gmail.connector import GmailCheckpoint
from onyx.connectors.gmail.connector import GmailConnector
from onyx.connectors.gmail.connector import thread_to_document
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
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


def test_time_str_to_utc() -> None:
    str_to_dt = {
        "Tue, 5 Oct 2021 09:38:25 GMT": datetime.datetime(
            2021, 10, 5, 9, 38, 25, tzinfo=datetime.timezone.utc
        ),
        "Sat, 24 Jul 2021 09:21:20 +0000 (UTC)": datetime.datetime(
            2021, 7, 24, 9, 21, 20, tzinfo=datetime.timezone.utc
        ),
        "Thu, 29 Jul 2021 04:20:37 -0400 (EDT)": datetime.datetime(
            2021, 7, 29, 8, 20, 37, tzinfo=datetime.timezone.utc
        ),
        "30 Jun 2023 18:45:01 +0300": datetime.datetime(
            2023, 6, 30, 15, 45, 1, tzinfo=datetime.timezone.utc
        ),
        "22 Mar 2020 20:12:18 +0000 (GMT)": datetime.datetime(
            2020, 3, 22, 20, 12, 18, tzinfo=datetime.timezone.utc
        ),
        "Date: Wed, 27 Aug 2025 11:40:00 +0200": datetime.datetime(
            2025, 8, 27, 9, 40, 0, tzinfo=datetime.timezone.utc
        ),
    }
    for strptime, expected_datetime in str_to_dt.items():
        assert time_str_to_utc(strptime) == expected_datetime


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
            q: str | None = None,
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
