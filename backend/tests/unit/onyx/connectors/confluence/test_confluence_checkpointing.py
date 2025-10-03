import time
from collections.abc import Callable
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from requests.exceptions import HTTPError

from onyx.configs.constants import DocumentSource
from onyx.connectors.confluence.connector import ConfluenceCheckpoint
from onyx.connectors.confluence.connector import ConfluenceConnector
from onyx.connectors.confluence.onyx_confluence import OnyxConfluence
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import SlimDocument
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector
from tests.unit.onyx.connectors.utils import (
    load_everything_from_checkpoint_connector_from_checkpoint,
)

PAGE_SIZE = 2


@pytest.fixture
def confluence_base_url() -> str:
    return "https://example.atlassian.net/wiki"


@pytest.fixture
def space_key() -> str:
    return "TEST"


@pytest.fixture
def mock_confluence_client() -> OnyxConfluence:
    """Create a mock Confluence client with proper typing"""
    # Server mode just Also updates the start value
    return OnyxConfluence(
        is_cloud=False, url="test", credentials_provider=MagicMock(), timeout=None
    )


@pytest.fixture
def confluence_connector(
    confluence_base_url: str, space_key: str, mock_confluence_client: OnyxConfluence
) -> Generator[ConfluenceConnector, None, None]:
    """Create a Confluence connector with a mock client"""
    # NOTE: we test with is_cloud=False for all tests, which is generally fine because the behavior
    # for the two versions is "close enough". If cloud-specific behavior is added, we can parametrize
    # the connector and client fixtures to allow either.
    connector = ConfluenceConnector(
        wiki_base=confluence_base_url,
        space=space_key,
        is_cloud=False,
        labels_to_skip=["secret", "sensitive"],
        timezone_offset=0.0,
        batch_size=2,
    )
    # Initialize the client directly
    connector._confluence_client = mock_confluence_client
    with patch("onyx.connectors.confluence.connector._SLIM_DOC_BATCH_SIZE", 2):
        yield connector


@pytest.fixture
def create_mock_page() -> Callable[..., dict[str, Any]]:
    def _create_mock_page(
        id: str = "123",
        title: str = "Test Page",
        updated: str = "2023-01-01T12:00:00.000+0000",
        content: str = "Test Content",
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Helper to create a mock Confluence page object"""
        return {
            "id": id,
            "title": title,
            "version": {"when": updated},
            "history": {"lastUpdated": {"when": updated}},
            "body": {"storage": {"value": content}},
            "metadata": {
                "labels": {"results": [{"name": label} for label in (labels or [])]}
            },
            "space": {"key": "TEST"},
            "_links": {"webui": f"/spaces/TEST/pages/{id}"},
        }

    return _create_mock_page


def test_get_cql_query_with_space(confluence_connector: ConfluenceConnector) -> None:
    """Test CQL query generation with space specified"""
    start = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp()
    end = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()

    query = confluence_connector._construct_page_cql_query(start, end)

    # Check that the space part and time part are both in the query
    assert f"space='{confluence_connector.space}'" in query
    assert "lastmodified >= '2023-01-01 00:00'" in query
    assert "lastmodified <= '2023-01-02 00:00'" in query
    assert " and " in query.lower()


def test_get_cql_query_without_space(confluence_base_url: str) -> None:
    """Test CQL query generation without space specified"""
    # Create connector without space key
    connector = ConfluenceConnector(wiki_base=confluence_base_url, is_cloud=True)

    start = datetime(2023, 1, 1, tzinfo=connector.timezone).timestamp()
    end = datetime(2023, 1, 2, tzinfo=connector.timezone).timestamp()

    query = connector._construct_page_cql_query(start, end)

    # Check that only time part is in the query
    assert "space=" not in query
    assert "lastmodified >= '2023-01-01 00:00'" in query
    assert "lastmodified <= '2023-01-02 00:00'" in query


def test_load_from_checkpoint_happy_path(
    confluence_connector: ConfluenceConnector,
    create_mock_page: Callable[..., dict[str, Any]],
) -> None:
    """Test loading from checkpoint - happy path"""
    # Set up mocked pages
    first_updated = datetime(2023, 1, 1, 12, 0, tzinfo=timezone.utc)
    last_updated = datetime(2023, 1, 3, 12, 0, tzinfo=timezone.utc)
    mock_page1 = create_mock_page(
        id="1", title="Page 1", updated=first_updated.isoformat()
    )
    mock_page2 = create_mock_page(
        id="2", title="Page 2", updated=first_updated.isoformat()
    )
    mock_page3 = create_mock_page(
        id="3", title="Page 3", updated=last_updated.isoformat()
    )

    # Mock paginated_cql_retrieval to return our mock pages
    confluence_client = confluence_connector._confluence_client
    assert confluence_client is not None, "bad test setup"
    get_mock = MagicMock()
    confluence_client.get = get_mock  # type: ignore
    get_mock.side_effect = [
        # First page response
        MagicMock(
            json=lambda: {
                "results": [mock_page1, mock_page2],
                "_links": {"next": "rest/api/content/search?cql=type=page&start=2"},
            }
        ),
        # links and attachemnts responses
        MagicMock(json=lambda: {"results": []}),
        MagicMock(json=lambda: {"results": []}),
        MagicMock(json=lambda: {"results": []}),
        MagicMock(json=lambda: {"results": []}),
        # next actual page response
        MagicMock(json=lambda: {"results": [mock_page3]}),
        # more links and attachment responses
        MagicMock(json=lambda: {"results": []}),
        MagicMock(json=lambda: {"results": []}),
        MagicMock(json=lambda: {"results": []}),
        MagicMock(json=lambda: {"results": []}),
    ]

    # Call load_from_checkpoint
    end_time = time.time()
    outputs = load_everything_from_checkpoint_connector(
        confluence_connector, 0, end_time
    )

    # Check that the documents were returned
    assert len(outputs) == 2

    checkpoint_output1 = outputs[0]
    assert len(checkpoint_output1.items) == 2
    document1 = checkpoint_output1.items[0]
    assert isinstance(document1, Document)
    assert document1.id == f"{confluence_connector.wiki_base}/spaces/TEST/pages/1"
    document2 = checkpoint_output1.items[1]
    assert isinstance(document2, Document)
    assert document2.id == f"{confluence_connector.wiki_base}/spaces/TEST/pages/2"
    assert checkpoint_output1.next_checkpoint == ConfluenceCheckpoint(
        has_more=True, next_page_url="rest/api/content/search?cql=type%3Dpage&start=2"
    )

    checkpoint_output2 = outputs[1]
    assert len(checkpoint_output2.items) == 1
    document3 = checkpoint_output2.items[0]
    assert isinstance(document3, Document)
    assert document3.id == f"{confluence_connector.wiki_base}/spaces/TEST/pages/3"
    assert not checkpoint_output2.next_checkpoint.has_more


def test_load_from_checkpoint_with_page_processing_error(
    confluence_connector: ConfluenceConnector,
    create_mock_page: Callable[..., dict[str, Any]],
) -> None:
    """Test loading from checkpoint with a mix of successful and failed page processing"""
    # Set up mocked pages
    mock_page1 = create_mock_page(id="1", title="Page 1")
    mock_page2 = create_mock_page(id="2", title="Page 2")

    # Mock paginated_cql_retrieval to return our mock pages
    confluence_client = confluence_connector._confluence_client
    assert confluence_client is not None, "bad test setup"
    get_mock = MagicMock()
    confluence_client.get = get_mock  # type: ignore
    get_mock.side_effect = [
        # First page response
        MagicMock(
            json=lambda: {
                "results": [mock_page1, mock_page2],
                "_links": {"next": "rest/api/content/search?cql=type=page&start=2"},
            }
        ),
        # Comments for page 1
        MagicMock(json=lambda: {"results": []}),
        # Attachments for page 1
        MagicMock(json=lambda: {"results": []}),
        # Comments for page 2
        MagicMock(json=lambda: {"results": []}),
        # Attachments for page 2
        MagicMock(json=lambda: {"results": []}),
        # Second page response (empty)
        MagicMock(
            json=lambda: {
                "results": [],
                "_links": {},
            }
        ),
    ]

    # Mock _convert_page_to_document to fail for the second page
    def mock_convert_side_effect(page: dict[str, Any]) -> Document | ConnectorFailure:
        if page["id"] == "1":
            return Document(
                id=f"{confluence_connector.wiki_base}/spaces/TEST/pages/1",
                sections=[],
                source=DocumentSource.CONFLUENCE,
                semantic_identifier="Page 1",
                metadata={},
            )
        else:
            return ConnectorFailure(
                failed_document=DocumentFailure(
                    document_id=page["id"],
                    document_link=f"{confluence_connector.wiki_base}/spaces/TEST/pages/{page['id']}",
                ),
                failure_message="Failed to process Confluence page",
                exception=Exception("Test error"),
            )

    with patch(
        "onyx.connectors.confluence.connector.ConfluenceConnector._convert_page_to_document",
        side_effect=mock_convert_side_effect,
    ):
        # Call load_from_checkpoint
        end_time = time.time()
        outputs = load_everything_from_checkpoint_connector(
            confluence_connector, 0, end_time
        )

        assert len(outputs) == 1
        checkpoint_output = outputs[0]
        assert len(checkpoint_output.items) == 2

        # First item should be successful
        assert isinstance(checkpoint_output.items[0], Document)
        assert (
            checkpoint_output.items[0].id
            == f"{confluence_connector.wiki_base}/spaces/TEST/pages/1"
        )

        # Second item should be a failure
        assert isinstance(checkpoint_output.items[1], ConnectorFailure)
        assert (
            "Failed to process Confluence page"
            in checkpoint_output.items[1].failure_message
        )


def test_retrieve_all_slim_docs_perm_sync(
    confluence_connector: ConfluenceConnector,
    create_mock_page: Callable[..., dict[str, Any]],
) -> None:
    """Test retrieving all slim documents"""
    # Set up mocked pages
    mock_page1 = create_mock_page(id="1")
    mock_page2 = create_mock_page(id="2")

    # Mock paginated_cql_retrieval to return our mock pages
    confluence_client = confluence_connector._confluence_client
    assert confluence_client is not None, "bad test setup"

    get_mock = MagicMock()
    confluence_client.get = get_mock  # type: ignore
    get_mock.side_effect = [
        # First page response
        MagicMock(
            json=lambda: {
                "results": [mock_page1, mock_page2],
                "_links": {"next": "rest/api/content/search?cql=type=page&start=2"},
            }
        ),
        # links and attachments responses
        MagicMock(json=lambda: {"results": []}),
        MagicMock(json=lambda: {"results": []}),
        MagicMock(json=lambda: {"results": []}),
    ]

    # Call retrieve_all_slim_docs_perm_sync
    batches = list(confluence_connector.retrieve_all_slim_docs_perm_sync(0, 100))
    assert get_mock.call_count == 4

    # Check that a batch with 2 documents was returned
    assert len(batches) == 1
    assert len(batches[0]) == 2
    assert isinstance(batches[0][0], SlimDocument)
    assert batches[0][0].id == f"{confluence_connector.wiki_base}/spaces/TEST/pages/1"
    assert batches[0][1].id == f"{confluence_connector.wiki_base}/spaces/TEST/pages/2"


@pytest.mark.parametrize(
    "status_code,expected_exception,expected_message",
    [
        (
            401,
            CredentialExpiredError,
            "Invalid or expired Confluence credentials",
        ),
        (
            403,
            InsufficientPermissionsError,
            "Insufficient permissions to access Confluence resources",
        ),
        (404, UnexpectedValidationError, "Unexpected Confluence error"),
    ],
)
def test_validate_connector_settings_errors(
    confluence_connector: ConfluenceConnector,
    status_code: int,
    expected_exception: type[Exception],
    expected_message: str,
) -> None:
    """Test validation with various error scenarios"""
    error = HTTPError(response=MagicMock(status_code=status_code))

    confluence_client = MagicMock()
    confluence_connector._low_timeout_confluence_client = confluence_client
    get_all_spaces_mock = cast(MagicMock, confluence_client.get_all_spaces)
    get_all_spaces_mock.side_effect = error

    with pytest.raises(expected_exception) as excinfo:
        confluence_connector.validate_connector_settings()
    assert expected_message in str(excinfo.value)


def test_validate_connector_settings_success(
    confluence_connector: ConfluenceConnector,
) -> None:
    """Test successful validation"""
    confluence_client = MagicMock()
    confluence_connector._low_timeout_confluence_client = confluence_client
    get_all_spaces_mock = cast(MagicMock, confluence_client.get_all_spaces)
    get_all_spaces_mock.return_value = {"results": [{"key": "TEST"}]}

    confluence_connector.validate_connector_settings()
    get_all_spaces_mock.assert_called_once()


def test_checkpoint_progress(
    confluence_connector: ConfluenceConnector,
    create_mock_page: Callable[..., dict[str, Any]],
) -> None:
    """Test that the checkpoint's last_updated field is properly updated after processing pages
    and that processed document IDs are stored to avoid reprocessing."""
    # Set up mocked pages with different timestamps
    earlier_timestamp = datetime(2023, 1, 1, 12, 0, tzinfo=timezone.utc)
    later_timestamp = datetime(2023, 1, 2, 12, 0, tzinfo=timezone.utc)
    latest_timestamp = datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc)
    mock_page1 = create_mock_page(
        id="1", title="Page 1", updated=earlier_timestamp.isoformat()
    )
    mock_page2 = create_mock_page(
        id="2", title="Page 2", updated=later_timestamp.isoformat()
    )
    mock_page3 = create_mock_page(
        id="3", title="Page 3", updated=latest_timestamp.isoformat()
    )

    # Mock paginated_cql_retrieval to return our mock pages
    confluence_client = confluence_connector._confluence_client
    assert confluence_client is not None, "bad test setup"
    get_mock = MagicMock()
    confluence_client.get = get_mock  # type: ignore
    get_mock.side_effect = [
        # First page response
        MagicMock(
            json=lambda: {
                "results": [mock_page1, mock_page2],
                "_links": {"next": "rest/api/content/search?cql=type=page&start=2"},
            }
        ),
        MagicMock(json=lambda: {"results": []}),
        MagicMock(json=lambda: {"results": []}),
        MagicMock(json=lambda: {"results": []}),
        MagicMock(json=lambda: {"results": []}),
        MagicMock(json=lambda: {"results": []}),
    ]

    # First run - process both pages
    end_time = datetime(2023, 1, 3, tzinfo=timezone.utc).timestamp()
    outputs = load_everything_from_checkpoint_connector(
        confluence_connector, 0, end_time
    )

    first_checkpoint = outputs[0].next_checkpoint

    assert (
        first_checkpoint.next_page_url
        == "rest/api/content/search?cql=type%3Dpage&start=2"
    )
    assert not outputs[-1].next_checkpoint.has_more

    assert len(outputs[0].items) == 2
    assert isinstance(outputs[0].items[0], Document)
    assert outputs[0].items[0].semantic_identifier == "Page 1"
    assert isinstance(outputs[0].items[1], Document)
    assert outputs[0].items[1].semantic_identifier == "Page 2"

    # Second run - same time range but with checkpoint from first run
    # Reset the mock to return the same pages
    get_mock.side_effect = [
        # First page response
        MagicMock(
            json=lambda: {
                "results": [mock_page3],
                "_links": {"next": "rest/api/content/search?cql=type=page&start=3"},
            }
        ),
        MagicMock(json=lambda: {"results": []}),
        MagicMock(json=lambda: {"results": []}),
        MagicMock(json=lambda: {"results": []}),
    ]

    # Use the checkpoint from first run
    first_checkpoint.has_more = True
    outputs_with_checkpoint = load_everything_from_checkpoint_connector_from_checkpoint(
        confluence_connector, 0, end_time, first_checkpoint
    )

    # Verify only the new page was processed since the others were in last_seen_doc_ids
    assert len(outputs_with_checkpoint) == 2
    assert len(outputs_with_checkpoint[0].items) == 1
    assert isinstance(outputs_with_checkpoint[0].items[0], Document)
    assert outputs_with_checkpoint[0].items[0].semantic_identifier == "Page 3"
    assert not outputs_with_checkpoint[-1].next_checkpoint.has_more
