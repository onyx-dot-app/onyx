from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

from onyx.configs.constants import DocumentSource
from onyx.connectors.google_chat.connector import (
    GoogleChatConnector,
    _message_to_document,
)
from onyx.connectors.models import Document


class _FakeRequest:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response

    def execute(self) -> dict[str, Any]:
        return self.response


class _FakeMessages:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def list(self, **kwargs: Any) -> _FakeRequest:
        self.calls.append(kwargs)
        page_token = kwargs.get("pageToken")
        if page_token == "messages-page-2":
            return _FakeRequest(
                {
                    "messages": [
                        {
                            "name": "spaces/AAA/messages/second",
                            "text": "Second message",
                            "createTime": "2026-01-02T12:00:00Z",
                            "sender": {"displayName": "Grace"},
                        }
                    ]
                }
            )
        return _FakeRequest(
            {
                "messages": [
                    {
                        "name": "spaces/AAA/messages/first",
                        "text": "First message",
                        "createTime": "2026-01-02T10:00:00Z",
                        "sender": {"displayName": "Ada"},
                    },
                    {
                        "name": "spaces/AAA/messages/card-only",
                        "createTime": "2026-01-02T11:00:00Z",
                    },
                ],
                "nextPageToken": "messages-page-2",
            }
        )


class _FakeSpaces:
    def __init__(self) -> None:
        self.messages_api = _FakeMessages()
        self.calls: list[dict[str, Any]] = []

    def list(self, **kwargs: Any) -> _FakeRequest:
        self.calls.append(kwargs)
        if kwargs.get("pageToken") == "spaces-page-2":
            return _FakeRequest(
                {"spaces": [{"name": "spaces/BBB", "displayName": "Support"}]}
            )
        return _FakeRequest(
            {
                "spaces": [{"name": "spaces/AAA", "displayName": "Engineering"}],
                "nextPageToken": "spaces-page-2",
            }
        )

    def messages(self) -> _FakeMessages:
        return self.messages_api


class _FakeChatService:
    def __init__(self) -> None:
        self.spaces_api = _FakeSpaces()

    def spaces(self) -> _FakeSpaces:
        return self.spaces_api


def test_message_to_document_preserves_searchable_context() -> None:
    document = _message_to_document(
        {
            "name": "spaces/AAA/messages/BBB",
            "text": "A deployment note",
            "createTime": "2026-01-02T10:00:00Z",
            "lastUpdateTime": "2026-01-02T10:05:00Z",
            "sender": {"displayName": "Ada"},
            "thread": {"name": "spaces/AAA/threads/CCC"},
        },
        {"name": "spaces/AAA", "displayName": "Engineering"},
    )

    assert document.id == "GOOGLE_CHAT_spaces/AAA/messages/BBB"
    assert document.source == DocumentSource.GOOGLE_CHAT
    assert document.semantic_identifier == "Ada in Engineering: A deployment note"
    assert document.title == "Engineering"
    assert document.sections[0].text == "A deployment note"
    assert document.sections[0].link == "https://chat.google.com/room/AAA"
    assert document.metadata == {
        "Space": "Engineering",
        "Sender": "Ada",
        "Thread": "spaces/AAA/threads/CCC",
    }
    assert document.doc_created_at == datetime(2026, 1, 2, 10, 0, tzinfo=timezone.utc)
    assert document.doc_updated_at == datetime(2026, 1, 2, 10, 5, tzinfo=timezone.utc)


def test_connector_paginates_and_filters_spaces_and_messages() -> None:
    connector = GoogleChatConnector(
        space_names=["Engineering"],
        start_date="2026-01-01",
        batch_size=1,
    )
    fake_service = _FakeChatService()

    with patch.object(connector, "_chat_service", return_value=fake_service):
        batches = list(
            connector.poll_source(
                datetime(2025, 12, 1, tzinfo=timezone.utc).timestamp(),
                datetime(2026, 2, 1, tzinfo=timezone.utc).timestamp(),
            )
        )

    documents = [document for batch in batches for document in batch]
    assert all(isinstance(document, Document) for document in documents)
    assert [
        document.id for document in documents if isinstance(document, Document)
    ] == [
        "GOOGLE_CHAT_spaces/AAA/messages/first",
        "GOOGLE_CHAT_spaces/AAA/messages/second",
    ]
    assert len(fake_service.spaces_api.calls) == 2
    assert len(fake_service.spaces_api.messages_api.calls) == 2
    first_message_call = fake_service.spaces_api.messages_api.calls[0]
    assert first_message_call["parent"] == "spaces/AAA"
    assert first_message_call["filter"] == (
        'createTime > "2026-01-01T00:00:00Z" AND createTime < "2026-02-01T00:00:00Z"'
    )
    assert first_message_call["orderBy"] == "ASC"
