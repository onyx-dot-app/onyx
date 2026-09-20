from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    InsufficientPermissionsError,
)
from onyx.connectors.google_chat.connector import (
    GoogleChatConnector,
    _message_to_document,
)
from onyx.connectors.models import Document


def _request(response: dict[str, object]) -> MagicMock:
    request = MagicMock()
    request.execute.return_value = response
    return request


def _fake_chat_service() -> tuple[MagicMock, MagicMock, MagicMock]:
    service = MagicMock()
    spaces = MagicMock()
    messages = MagicMock()
    service.spaces.return_value = spaces
    spaces.messages.return_value = messages
    spaces.list.side_effect = [
        _request(
            {
                "spaces": [{"name": "spaces/AAA", "displayName": "Engineering"}],
                "nextPageToken": "spaces-page-2",
            }
        ),
        _request({"spaces": [{"name": "spaces/BBB", "displayName": "Support"}]}),
    ]
    messages.list.side_effect = [
        _request(
            {
                "messages": [
                    {
                        "name": "spaces/AAA/messages/first",
                        "text": "First message",
                        "createTime": "2026-01-02T10:00:00Z",
                        "sender": {"displayName": "Ada"},
                    },
                    {"name": "spaces/AAA/messages/card-only"},
                ],
                "nextPageToken": "messages-page-2",
            }
        ),
        _request(
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
        ),
    ]
    return service, spaces, messages


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
    fake_service, spaces_api, messages_api = _fake_chat_service()

    with patch.object(connector, "_chat_service", return_value=fake_service):
        batches = list(
            connector.poll_source(
                datetime(2025, 12, 1, tzinfo=timezone.utc).timestamp(),
                datetime(2026, 2, 1, tzinfo=timezone.utc).timestamp(),
            )
        )

    documents = [document for batch in batches for document in batch]
    assert len(batches) == 2
    assert [
        document.id for document in documents if isinstance(document, Document)
    ] == [
        "GOOGLE_CHAT_spaces/AAA/messages/first",
        "GOOGLE_CHAT_spaces/AAA/messages/second",
    ]
    assert spaces_api.list.call_args_list[1].kwargs["pageToken"] == "spaces-page-2"
    assert messages_api.list.call_args_list[1].kwargs["pageToken"] == "messages-page-2"
    first_message_call = messages_api.list.call_args_list[0].kwargs
    assert first_message_call["filter"] == (
        'createTime > "2026-01-01T00:00:00Z" AND createTime < "2026-02-01T00:00:00Z"'
    )
    assert first_message_call["orderBy"] == "ASC"


@pytest.mark.parametrize("service_account_value", [None, "not JSON", "[]"])
def test_connector_rejects_invalid_service_account_json(
    service_account_value: str | None,
) -> None:
    connector = GoogleChatConnector()

    with pytest.raises(CredentialInvalidError):
        connector.load_credentials(
            {"google_chat_service_account_secret": service_account_value}
        )


def test_connector_validation_requires_matching_space() -> None:
    connector = GoogleChatConnector(space_names=["Missing space"])
    fake_service, _, _ = _fake_chat_service()

    with (
        patch.object(connector, "_chat_service", return_value=fake_service),
        pytest.raises(ConnectorValidationError, match="No accessible Google Chat"),
    ):
        connector.validate_connector_settings()


def test_connector_validation_reports_missing_message_scope() -> None:
    connector = GoogleChatConnector()
    fake_service, _, messages_api = _fake_chat_service()
    forbidden_error = HttpError(Response({"status": "403"}), b"forbidden")
    messages_api.list.side_effect = None
    messages_api.list.return_value.execute.side_effect = forbidden_error

    with (
        patch.object(connector, "_chat_service", return_value=fake_service),
        pytest.raises(InsufficientPermissionsError, match="administrator approved"),
    ):
        connector.validate_connector_settings()
