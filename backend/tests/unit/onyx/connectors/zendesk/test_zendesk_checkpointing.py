import time
from collections.abc import Callable
from collections.abc import Generator
from typing import Any
from typing import cast
from unittest.mock import call
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from requests.exceptions import HTTPError

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.models import Document
from onyx.connectors.zendesk.connector import ZendeskClient
from onyx.connectors.zendesk.connector import ZendeskConnector
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector


@pytest.fixture
def mock_zendesk_client() -> MagicMock:
    """Create a mock Zendesk client"""
    mock = MagicMock(spec=ZendeskClient)
    mock.base_url = "https://test.zendesk.com/api/v2"
    mock.auth = ("test@example.com/token", "test_token")
    mock.make_request = MagicMock()
    return mock


@pytest.fixture
def zendesk_connector(
    mock_zendesk_client: MagicMock,
) -> Generator[ZendeskConnector, None, None]:
    """Create a Zendesk connector with mocked client"""
    connector = ZendeskConnector(content_type="articles")
    connector.client = mock_zendesk_client
    yield connector


@pytest.fixture
def unmocked_zendesk_connector() -> Generator[ZendeskConnector, None, None]:
    """Create a Zendesk connector with unmocked client"""
    zendesk_connector = ZendeskConnector(content_type="articles")
    zendesk_connector.client = ZendeskClient(
        "test", "test@example.com/token", "test_token"
    )
    yield zendesk_connector


@pytest.fixture
def create_mock_article() -> Callable[..., dict[str, Any]]:
    def _create_mock_article(
        id: int = 1,
        title: str = "Test Article",
        body: str = "Test Content",
        updated_at: str = "2023-01-01T12:00:00Z",
        author_id: str = "123",
        label_names: list[str] | None = None,
        draft: bool = False,
    ) -> dict[str, Any]:
        """Helper to create a mock article"""
        return {
            "id": id,
            "title": title,
            "body": body,
            "updated_at": updated_at,
            "author_id": author_id,
            "label_names": label_names or [],
            "draft": draft,
            "html_url": f"https://test.zendesk.com/hc/en-us/articles/{id}",
        }

    return _create_mock_article


@pytest.fixture
def create_mock_ticket() -> Callable[..., dict[str, Any]]:
    def _create_mock_ticket(
        id: int = 1,
        subject: str = "Test Ticket",
        description: str = "Test Description",
        updated_at: str = "2023-01-01T12:00:00Z",
        submitter_id: str = "123",
        status: str = "open",
        priority: str = "normal",
        tags: list[str] | None = None,
        ticket_type: str = "question",
    ) -> dict[str, Any]:
        """Helper to create a mock ticket"""
        return {
            "id": id,
            "subject": subject,
            "description": description,
            "updated_at": updated_at,
            "submitter": submitter_id,
            "status": status,
            "priority": priority,
            "tags": tags or [],
            "type": ticket_type,
            "url": f"https://test.zendesk.com/agent/tickets/{id}",
        }

    return _create_mock_ticket


@pytest.fixture
def create_mock_author() -> Callable[..., dict[str, Any]]:
    def _create_mock_author(
        id: str = "123",
        name: str = "Test User",
        email: str = "test@example.com",
    ) -> dict[str, Any]:
        """Helper to create a mock author"""
        return {
            "user": {
                "id": id,
                "name": name,
                "email": email,
            }
        }

    return _create_mock_author


def test_load_from_checkpoint_articles_happy_path(
    zendesk_connector: ZendeskConnector,
    mock_zendesk_client: MagicMock,
    create_mock_article: Callable[..., dict[str, Any]],
    create_mock_author: Callable[..., dict[str, Any]],
) -> None:
    """Test loading articles from checkpoint - happy path"""
    # Set up mock responses
    mock_article1 = create_mock_article(id=1, title="Article 1")
    mock_article2 = create_mock_article(id=2, title="Article 2")
    mock_author = create_mock_author()

    # Mock API responses
    mock_zendesk_client.make_request.side_effect = [
        # First call: content tags
        {"records": []},
        # Second call: articles page
        {
            "articles": [mock_article1, mock_article2],
            "meta": {
                "has_more": False,
                "after_cursor": None,
            },
        },
        # Third call: author info
        mock_author,
    ]

    # Call load_from_checkpoint
    end_time = time.time()
    outputs = load_everything_from_checkpoint_connector(zendesk_connector, 0, end_time)

    # Check that we got the documents
    assert len(outputs) == 2
    assert outputs[0].next_checkpoint.cached_content_tags is not None

    assert len(outputs[1].items) == 2

    # Check first document
    doc1 = outputs[1].items[0]
    assert isinstance(doc1, Document)
    assert doc1.id == "article:1"
    assert doc1.semantic_identifier == "Article 1"
    assert doc1.source == DocumentSource.ZENDESK

    # Check second document
    doc2 = outputs[1].items[1]
    assert isinstance(doc2, Document)
    assert doc2.id == "article:2"
    assert doc2.semantic_identifier == "Article 2"
    assert doc2.source == DocumentSource.ZENDESK

    # Check checkpoint state
    assert not outputs[1].next_checkpoint.has_more


def test_load_from_checkpoint_tickets_happy_path(
    zendesk_connector: ZendeskConnector,
    mock_zendesk_client: MagicMock,
    create_mock_ticket: Callable[..., dict[str, Any]],
    create_mock_author: Callable[..., dict[str, Any]],
) -> None:
    """Test loading tickets from checkpoint - happy path"""
    # Configure connector for tickets
    zendesk_connector.content_type = "tickets"

    # Set up mock responses
    mock_ticket1 = create_mock_ticket(id=1, subject="Ticket 1")
    mock_ticket2 = create_mock_ticket(id=2, subject="Ticket 2")
    mock_author = create_mock_author()

    # Mock API responses
    mock_zendesk_client.make_request.side_effect = [
        # First call: content tags
        {"records": []},
        # Second call: tickets page
        {
            "tickets": [mock_ticket1, mock_ticket2],
            "end_of_stream": True,
            "end_time": int(time.time()),
        },
        # Third call: author info
        mock_author,
        # Fourth call: comments page
        {"comments": []},
        # Fifth call: comments page
        {"comments": []},
    ]

    zendesk_connector.client = mock_zendesk_client

    # Call load_from_checkpoint
    end_time = time.time()
    outputs = load_everything_from_checkpoint_connector(zendesk_connector, 0, end_time)

    # Check that we got the documents
    assert len(outputs) == 2
    assert outputs[0].next_checkpoint.cached_content_tags is not None
    assert len(outputs[1].items) == 2

    # Check first document
    doc1 = outputs[1].items[0]
    print(doc1, type(doc1))
    assert isinstance(doc1, Document)
    assert doc1.id == "zendesk_ticket_1"
    assert doc1.semantic_identifier == "Ticket #1: Ticket 1"
    assert doc1.source == DocumentSource.ZENDESK

    # Check second document
    doc2 = outputs[1].items[1]
    assert isinstance(doc2, Document)
    assert doc2.id == "zendesk_ticket_2"
    assert doc2.semantic_identifier == "Ticket #2: Ticket 2"
    assert doc2.source == DocumentSource.ZENDESK

    # Check checkpoint state
    assert not outputs[1].next_checkpoint.has_more


def test_load_from_checkpoint_with_rate_limit(
    unmocked_zendesk_connector: ZendeskConnector,
    create_mock_article: Callable[..., dict[str, Any]],
    create_mock_author: Callable[..., dict[str, Any]],
) -> None:
    """Test loading from checkpoint with rate limit handling"""
    zendesk_connector = unmocked_zendesk_connector
    # Set up mock responses
    mock_article = create_mock_article()
    mock_author = create_mock_author()
    author_response = MagicMock()
    author_response.status_code = 200
    author_response.json.return_value = mock_author

    # Create mock responses for requests.get
    rate_limit_response = MagicMock()
    rate_limit_response.status_code = 429
    rate_limit_response.headers = {"Retry-After": "60"}
    rate_limit_response.raise_for_status.side_effect = HTTPError(
        response=rate_limit_response
    )

    success_response = MagicMock()
    success_response.status_code = 200
    success_response.json.return_value = {
        "articles": [mock_article],
        "meta": {
            "has_more": False,
            "after_cursor": None,
        },
    }

    # Mock requests.get to simulate rate limit then success
    with patch("onyx.connectors.zendesk.connector.requests.get") as mock_get:
        mock_get.side_effect = [
            # First call: content tags
            MagicMock(
                status_code=200,
                json=lambda: {"records": [], "meta": {"has_more": False}},
            ),
            # Second call: articles page (rate limited)
            rate_limit_response,
            # Third call: articles page (after rate limit)
            success_response,
            # Fourth call: author info
            author_response,
        ]

        # Call load_from_checkpoint
        end_time = time.time()
        with patch("onyx.connectors.zendesk.connector.time.sleep") as mock_sleep:
            outputs = load_everything_from_checkpoint_connector(
                zendesk_connector, 0, end_time
            )
            mock_sleep.assert_has_calls([call(60), call(0.1)])

        # Check that we got the document after rate limit was handled
        assert len(outputs) == 2
        assert outputs[0].next_checkpoint.cached_content_tags is not None
        assert len(outputs[1].items) == 1
        assert isinstance(outputs[1].items[0], Document)
        assert outputs[1].items[0].id == "article:1"

        # Verify the requests were made with correct parameters
        assert mock_get.call_count == 4
        # First call should be for content tags
        args, kwargs = mock_get.call_args_list[0]
        assert "guide/content_tags" in args[0]
        # Second call should be for articles (rate limited)
        args, kwargs = mock_get.call_args_list[1]
        assert "help_center/articles" in args[0]
        # Third call should be for articles (success)
        args, kwargs = mock_get.call_args_list[2]
        assert "help_center/articles" in args[0]
        # Fourth call should be for author info
        args, kwargs = mock_get.call_args_list[3]
        assert "users/123" in args[0]


def test_load_from_checkpoint_with_empty_response(
    zendesk_connector: ZendeskConnector,
    mock_zendesk_client: MagicMock,
) -> None:
    """Test loading from checkpoint with empty response"""
    # Mock API responses
    mock_zendesk_client.make_request.side_effect = [
        # First call: content tags
        {"records": []},
        # Second call: empty articles page
        {
            "articles": [],
            "meta": {
                "has_more": False,
                "after_cursor": None,
            },
        },
    ]

    # Call load_from_checkpoint
    end_time = time.time()
    outputs = load_everything_from_checkpoint_connector(zendesk_connector, 0, end_time)

    # Check that we got no documents
    assert len(outputs) == 2
    assert outputs[0].next_checkpoint.cached_content_tags is not None
    assert len(outputs[1].items) == 0
    assert not outputs[1].next_checkpoint.has_more


def test_load_from_checkpoint_with_skipped_article(
    zendesk_connector: ZendeskConnector,
    mock_zendesk_client: MagicMock,
    create_mock_article: Callable[..., dict[str, Any]],
) -> None:
    """Test loading from checkpoint with an article that should be skipped"""
    # Set up mock responses with a draft article
    mock_article = create_mock_article(draft=True)
    mock_zendesk_client.make_request.side_effect = [
        # First call: content tags
        {"records": []},
        # Second call: articles page with draft article
        {
            "articles": [mock_article],
            "meta": {
                "has_more": False,
                "after_cursor": None,
            },
        },
    ]

    # Call load_from_checkpoint
    end_time = time.time()
    outputs = load_everything_from_checkpoint_connector(zendesk_connector, 0, end_time)

    # Check that no documents were returned
    assert len(outputs) == 2
    assert outputs[0].next_checkpoint.cached_content_tags is not None
    assert len(outputs[1].items) == 0
    assert not outputs[1].next_checkpoint.has_more


def test_load_from_checkpoint_with_skipped_ticket(
    zendesk_connector: ZendeskConnector,
    mock_zendesk_client: MagicMock,
    create_mock_ticket: Callable[..., dict[str, Any]],
) -> None:
    """Test loading from checkpoint with a deleted ticket"""
    # Configure connector for tickets
    zendesk_connector.content_type = "tickets"

    # Set up mock responses with a deleted ticket
    mock_ticket = create_mock_ticket(status="deleted")
    mock_zendesk_client.make_request.side_effect = [
        # First call: content tags
        {"records": []},
        # Second call: tickets page with deleted ticket
        {
            "tickets": [mock_ticket],
            "end_of_stream": True,
            "end_time": int(time.time()),
        },
    ]

    # Call load_from_checkpoint
    end_time = time.time()
    outputs = load_everything_from_checkpoint_connector(zendesk_connector, 0, end_time)

    # Check that no documents were returned
    assert len(outputs) == 2
    assert outputs[0].next_checkpoint.cached_content_tags is not None
    assert len(outputs[1].items) == 0
    assert not outputs[1].next_checkpoint.has_more


@pytest.mark.parametrize(
    "status_code,expected_exception,expected_message",
    [
        (
            401,
            CredentialExpiredError,
            "Your Zendesk credentials appear to be invalid or expired",
        ),
        (
            403,
            InsufficientPermissionsError,
            "Your Zendesk token does not have sufficient permissions",
        ),
        (
            404,
            ConnectorValidationError,
            "Zendesk resource not found",
        ),
    ],
)
def test_validate_connector_settings_errors(
    zendesk_connector: ZendeskConnector,
    status_code: int,
    expected_exception: type[Exception],
    expected_message: str,
) -> None:
    """Test validation with various error scenarios"""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    error = HTTPError(response=mock_response)

    mock_zendesk_client = cast(MagicMock, zendesk_connector.client)
    mock_zendesk_client.make_request.side_effect = error

    with pytest.raises(expected_exception) as excinfo:
        print("excinfo", excinfo)
        zendesk_connector.validate_connector_settings()

    assert expected_message in str(excinfo.value)


def test_validate_connector_settings_success(
    zendesk_connector: ZendeskConnector,
    mock_zendesk_client: MagicMock,
) -> None:
    """Test successful validation"""
    # Mock successful API response
    mock_zendesk_client.make_request.return_value = {
        "articles": [],
        "meta": {"has_more": False},
    }

    zendesk_connector.validate_connector_settings()
