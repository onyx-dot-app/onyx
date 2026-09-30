"""Round-trip tests for the Zendesk connector's DocumentFailure.document_id.

DocumentFailure.document_id must equal the Document.id that the connector would have
produced for the same source item. Several consumers match failures to documents by
that value, and a mismatch silently breaks all of them:

- backend/onyx/background/celery/tasks/docprocessing/tasks.py:
  `document.id not in failed_document_ids`
- backend/onyx/background/indexing/run_targeted_reindex.py:
  `{d.id for d in documents} - failed_ids`
- backend/onyx/background/celery/celery_utils.py: `_get_failure_id`

The Zendesk connector previously violated this invariant at both its article and
ticket failure sites: it emitted the bare numeric source id (e.g. "12345") on
failure, while the success path indexes documents with a type-prefixed id
(e.g. "article:12345" or "zendesk_ticket_12345"). These tests drive the connector
twice per content type, once so conversion succeeds and once so it raises, and
assert the resulting ids match.
"""

import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.connectors.models import ConnectorFailure, Document
from onyx.connectors.zendesk.connector import ZendeskConnector
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector


@pytest.fixture
def mock_zendesk_client() -> MagicMock:
    from onyx.connectors.zendesk.connector import ZendeskClient

    mock = MagicMock(spec=ZendeskClient)
    mock.base_url = "https://test.zendesk.com/api/v2"
    mock.auth = ("test@example.com/token", "test_token")
    mock.make_request = MagicMock()
    return mock


@pytest.fixture
def article_connector(mock_zendesk_client: MagicMock) -> ZendeskConnector:
    connector = ZendeskConnector(content_type="articles")
    connector.client = mock_zendesk_client
    return connector


@pytest.fixture
def ticket_connector(mock_zendesk_client: MagicMock) -> ZendeskConnector:
    connector = ZendeskConnector(content_type="tickets")
    connector.client = mock_zendesk_client
    return connector


def _mock_article(article_id: int) -> dict[str, Any]:
    return {
        "id": article_id,
        "title": "Test Article",
        "body": "Test Content",
        "updated_at": "2023-01-01T12:00:00Z",
        "author_id": "123",
        "label_names": [],
        "draft": False,
        "html_url": f"https://test.zendesk.com/hc/en-us/articles/{article_id}",
    }


def _mock_ticket(ticket_id: int) -> dict[str, Any]:
    return {
        "id": ticket_id,
        "subject": "Test Ticket",
        "description": "Test Description",
        "updated_at": "2023-01-01T12:00:00Z",
        "submitter": "123",
        "status": "open",
        "priority": "normal",
        "tags": [],
        "type": "question",
        "url": f"https://test.zendesk.com/agent/tickets/{ticket_id}",
    }


def _mock_author() -> dict[str, Any]:
    return {"user": {"id": "123", "name": "Test User", "email": "test@example.com"}}


def _run_articles(
    connector: ZendeskConnector, client: MagicMock, article_id: int
) -> list[Document | ConnectorFailure]:
    client.make_request.side_effect = [
        {"records": []},
        {
            "articles": [_mock_article(article_id)],
            "meta": {"has_more": False, "after_cursor": None},
        },
        _mock_author(),
    ]
    end_time = time.time()
    outputs = load_everything_from_checkpoint_connector(connector, 0, end_time)
    items: list[Document | ConnectorFailure] = []
    for output in outputs:
        items.extend(output.items)
    return items


def _run_tickets(
    connector: ZendeskConnector, client: MagicMock, ticket_id: int
) -> list[Document | ConnectorFailure]:
    client.make_request.side_effect = [
        {"records": []},
        {
            "tickets": [_mock_ticket(ticket_id)],
            "end_of_stream": True,
            "end_time": int(time.time()),
        },
        _mock_author(),
        {"comments": []},
        {"comments": []},
    ]
    end_time = time.time()
    outputs = load_everything_from_checkpoint_connector(connector, 0, end_time)
    items: list[Document | ConnectorFailure] = []
    for output in outputs:
        items.extend(output.items)
    return items


def test_article_failure_document_id_matches_success_document_id(
    article_connector: ZendeskConnector, mock_zendesk_client: MagicMock
) -> None:
    article_id = 555

    success_items = _run_articles(article_connector, mock_zendesk_client, article_id)
    documents = [item for item in success_items if isinstance(item, Document)]
    assert len(documents) == 1
    success_document_id = documents[0].id

    with patch(
        "onyx.connectors.zendesk.connector._article_to_document",
        side_effect=RuntimeError("boom"),
    ):
        failure_items = _run_articles(
            article_connector, mock_zendesk_client, article_id
        )

    failures = [item for item in failure_items if isinstance(item, ConnectorFailure)]
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    failure_document_id = failures[0].failed_document.document_id

    assert failure_document_id == success_document_id
    assert failure_document_id != str(article_id)


def test_ticket_failure_document_id_matches_success_document_id(
    ticket_connector: ZendeskConnector, mock_zendesk_client: MagicMock
) -> None:
    ticket_id = 777

    success_items = _run_tickets(ticket_connector, mock_zendesk_client, ticket_id)
    documents = [item for item in success_items if isinstance(item, Document)]
    assert len(documents) == 1
    success_document_id = documents[0].id

    with patch(
        "onyx.connectors.zendesk.connector._ticket_to_document",
        side_effect=RuntimeError("boom"),
    ):
        failure_items = _run_tickets(ticket_connector, mock_zendesk_client, ticket_id)

    failures = [item for item in failure_items if isinstance(item, ConnectorFailure)]
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    failure_document_id = failures[0].failed_document.document_id

    assert failure_document_id == success_document_id
    assert failure_document_id != str(ticket_id)
