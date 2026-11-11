from unittest.mock import MagicMock, patch
import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.shortcut.client import ShortcutClient
from onyx.connectors.shortcut.connector import (
    ShortcutConnector,
    _epic_to_document,
    _story_to_document,
)
from onyx.connectors.shortcut.models import (
    ShortcutComment,
    ShortcutEpic,
    ShortcutStory,
)


def test_story_to_document_transformation() -> None:
    story = ShortcutStory(
        id=123,
        name="Implement Shortcut Connector",
        description="Add a new connector for Shortcut app.",
        story_type="feature",
        epic_id=45,
        project_id=12,
        app_url="https://app.shortcut.com/workspace/story/123",
        created_at="2026-11-10T10:00:00Z",
        updated_at="2026-11-11T12:00:00Z",
        comments=[
            ShortcutComment(id=1, text="Initial design ready"),
            ShortcutComment(id=2, text="Implementation started"),
        ],
        labels=["backend", "connector"],
        completed=False,
    )

    doc = _story_to_document(story)

    assert doc.id == "shortcut_story_123"
    assert doc.source == DocumentSource.SHORTCUT
    assert doc.title == "Implement Shortcut Connector"
    assert doc.semantic_identifier == "Implement Shortcut Connector"
    assert doc.metadata["story_id"] == "123"
    assert doc.metadata["story_type"] == "feature"
    assert doc.metadata["epic_id"] == "45"
    assert doc.metadata["project_id"] == "12"
    assert doc.metadata["labels"] == ["backend", "connector"]
    assert doc.metadata["url"] == "https://app.shortcut.com/workspace/story/123"
    assert doc.doc_created_at is not None
    assert doc.doc_updated_at is not None
    assert len(doc.sections) == 2
    assert "Shortcut Story #123: Implement Shortcut Connector" in doc.sections[0].text
    assert "Comments:" in doc.sections[1].text
    assert "- Initial design ready" in doc.sections[1].text


def test_epic_to_document_transformation() -> None:
    epic = ShortcutEpic(
        id=789,
        name="Q4 Connectors Epic",
        description="Ship major connectors for productivity tools.",
        state="in progress",
        app_url="https://app.shortcut.com/workspace/epic/789",
        created_at="2026-10-01T00:00:00Z",
        updated_at="2026-11-01T15:30:00Z",
    )

    doc = _epic_to_document(epic)

    assert doc.id == "shortcut_epic_789"
    assert doc.source == DocumentSource.SHORTCUT
    assert doc.title == "Q4 Connectors Epic"
    assert doc.metadata["epic_id"] == "789"
    assert doc.metadata["state"] == "in progress"
    assert doc.metadata["url"] == "https://app.shortcut.com/workspace/epic/789"
    assert doc.doc_created_at is not None
    assert doc.doc_updated_at is not None
    assert "Shortcut Epic #789: Q4 Connectors Epic" in doc.sections[0].text


def test_shortcut_client_error_handling() -> None:
    client = ShortcutClient(api_token="dummy_token")

    with patch("requests.request") as mock_req:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_req.return_value = mock_resp
        with pytest.raises(CredentialExpiredError):
            client.validate_credentials()

    with patch("requests.request") as mock_req:
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_req.return_value = mock_resp
        with pytest.raises(InsufficientPermissionsError):
            client.get_epics()

    with patch("requests.request") as mock_req:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_req.return_value = mock_resp
        with pytest.raises(ConnectorValidationError):
            list(client.paginate_stories())


def test_shortcut_connector_missing_credentials() -> None:
    connector = ShortcutConnector()
    with pytest.raises(ConnectorMissingCredentialError):
        connector.validate_connector_settings()

    with pytest.raises(ConnectorMissingCredentialError):
        list(connector.load_from_state())

    with pytest.raises(ConnectorMissingCredentialError):
        list(connector.poll_source(start=0, end=1000000))


def test_shortcut_connector_load_from_state() -> None:
    connector = ShortcutConnector(batch_size=2)
    connector.load_credentials({"shortcut_api_token": "valid_token"})

    mock_epics = [
        ShortcutEpic(id=1, name="Epic 1"),
        ShortcutEpic(id=2, name="Epic 2"),
    ]
    mock_stories = [
        ShortcutStory(id=101, name="Story 1"),
        ShortcutStory(id=102, name="Story 2"),
        ShortcutStory(id=103, name="Story 3"),
    ]

    assert connector.client is not None
    connector.client.get_epics = MagicMock(return_value=mock_epics)  # type: ignore
    connector.client.paginate_stories = MagicMock(return_value=iter(mock_stories))  # type: ignore

    batches = list(connector.load_from_state())

    # Total 5 docs: batch 1 has 2 epics, batch 2 has 2 stories, batch 3 has 1 story
    total_docs = [doc for batch in batches for doc in batch]
    assert len(total_docs) == 5
    assert total_docs[0].id == "shortcut_epic_1"
    assert total_docs[1].id == "shortcut_epic_2"
    assert total_docs[2].id == "shortcut_story_101"
    assert total_docs[3].id == "shortcut_story_102"
    assert total_docs[4].id == "shortcut_story_103"


def test_shortcut_connector_poll_source() -> None:
    connector = ShortcutConnector(batch_size=10)
    connector.load_credentials({"shortcut_api_token": "valid_token"})

    mock_stories = [
        # Inside window [1000, 2000]
        ShortcutStory(id=201, name="In Window", updated_at="1970-01-01T00:25:00Z"),  # epoch 1500
        # Outside window
        ShortcutStory(id=202, name="Old Story", updated_at="1970-01-01T00:05:00Z"),  # epoch 300
    ]

    assert connector.client is not None
    connector.client.paginate_stories = MagicMock(return_value=iter(mock_stories))  # type: ignore

    batches = list(connector.poll_source(start=1000, end=2000))
    polled_docs = [doc for batch in batches for doc in batch]

    assert len(polled_docs) == 1
    assert polled_docs[0].id == "shortcut_story_201"
