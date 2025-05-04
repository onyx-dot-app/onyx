from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Dict
from typing import List
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import requests

from onyx.connectors.exceptions import CredentialInvalidError
from onyx.connectors.models import SlimDocument
from onyx.connectors.paperless_ngx.connector import CORRESPONDENTS_ENDPOINT
from onyx.connectors.paperless_ngx.connector import DOC_BATCH_SIZE
from onyx.connectors.paperless_ngx.connector import DOCUMENT_TYPES_ENDPOINT
from onyx.connectors.paperless_ngx.connector import DOCUMENTS_ENDPOINT
from onyx.connectors.paperless_ngx.connector import PaperlessNgxConnector
from onyx.connectors.paperless_ngx.connector import PROFILE_ENDPOINT
from onyx.connectors.paperless_ngx.connector import TAGS_ENDPOINT
from onyx.connectors.paperless_ngx.connector import USERS_ENDPOINT


@pytest.fixture
def connector() -> PaperlessNgxConnector:
    return PaperlessNgxConnector()


@pytest.fixture
def mock_document_response() -> Dict[str, Any]:
    return {
        "id": 1,
        "title": "Test Document",
        "content": "Test content",
        "created": "2023-01-01T00:00:00Z",
        "modified": "2023-01-02T00:00:00Z",
        "added": "2023-01-03T00:00:00Z",
        "original_file_name": "test.pdf",
        "download_url": f"{DOCUMENTS_ENDPOINT}1/download/",
        "thumbnail_url": f"{DOCUMENTS_ENDPOINT}1/thumb/",
        "correspondent": None,
        "document_type": None,
        "tags": [],
        "owner": None,
    }


@pytest.fixture
def mock_responses(
    mock_document_response: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "documents": [mock_document_response],
        "tags": [],
        "users": [],
        "correspondents": [],
        "document_types": [],
        "profile": {
            "first_name": "Test",
            "email": "test@example.com",
        },
    }


@pytest.fixture
def mock_get_side_effect(mock_responses: Dict[str, List[Dict[str, Any]]]) -> Any:
    def side_effect(url: str, **kwargs: Any) -> MagicMock:
        if PROFILE_ENDPOINT in url:
            return MagicMock(
                ok=True,
                json=lambda: mock_responses["profile"],
            )
        return MagicMock(
            ok=True,
            json=lambda: {
                "count": 1,
                "next": None,
                "results": (
                    mock_responses["documents"]
                    if DOCUMENTS_ENDPOINT in url
                    else (
                        mock_responses["tags"]
                        if TAGS_ENDPOINT in url
                        else (
                            mock_responses["users"]
                            if USERS_ENDPOINT in url
                            else (
                                mock_responses["correspondents"]
                                if CORRESPONDENTS_ENDPOINT in url
                                else mock_responses["document_types"]
                            )
                        )
                    )
                ),
            },
        )

    return side_effect


@pytest.fixture
def setup_connector(
    connector: PaperlessNgxConnector, mock_get_side_effect: Any
) -> PaperlessNgxConnector:
    with patch("requests.get") as mock_get:
        mock_get.side_effect = mock_get_side_effect
        credentials = {
            "paperless_ngx_api_url": "http://test.com",
            "paperless_ngx_auth_token": "test_token",
        }
        connector.load_credentials(credentials)
        return connector


def test_load_credentials(
    connector: PaperlessNgxConnector, mock_get_side_effect: Any
) -> None:
    with patch("requests.get") as mock_get:
        mock_get.side_effect = mock_get_side_effect
        credentials = {
            "paperless_ngx_api_url": "http://test.com",
            "paperless_ngx_auth_token": "test_token",
        }

        connector.load_credentials(credentials)

        assert connector.api_url == "http://test.com"
        assert connector.auth_token == "test_token"

        connector.validate_connector_settings()

        mock_get.assert_called_with(
            f"http://test.com{PROFILE_ENDPOINT}",
            headers={"Authorization": "Token test_token", "Accept": "application/json"},
        )


def test_load_from_state(
    setup_connector: PaperlessNgxConnector, mock_get_side_effect: Any
) -> None:
    with patch("requests.get") as mock_get:
        mock_get.side_effect = mock_get_side_effect

        docs = next(setup_connector.load_from_state())

        # Verify results
        assert len(docs) == 1
        doc = docs[0]
        assert doc.id == "1"
        assert doc.title == "Test Document"
        assert doc.source == "paperless_ngx"

        # Verify requests were made with correct headers and URLs
        expected_headers = {
            "Authorization": "Token test_token",
            "Accept": "application/json",
        }
        assert mock_get.call_count == 5  # One call for each endpoint
        mock_get.assert_any_call(
            f"http://test.com{DOCUMENTS_ENDPOINT}",
            headers=expected_headers,
            params={"limit": DOC_BATCH_SIZE},
        )
        mock_get.assert_any_call(
            f"http://test.com{TAGS_ENDPOINT}", headers=expected_headers, params={}
        )
        mock_get.assert_any_call(
            f"http://test.com{USERS_ENDPOINT}", headers=expected_headers, params={}
        )
        mock_get.assert_any_call(
            f"http://test.com{CORRESPONDENTS_ENDPOINT}",
            headers=expected_headers,
            params={},
        )
        mock_get.assert_any_call(
            f"http://test.com{DOCUMENT_TYPES_ENDPOINT}",
            headers=expected_headers,
            params={},
        )


def test_retrieve_all_slim_documents(
    setup_connector: PaperlessNgxConnector, mock_get_side_effect: Any
) -> None:
    with patch("requests.get") as mock_get:
        mock_get.side_effect = mock_get_side_effect

        docs = next(setup_connector.retrieve_all_slim_documents())

        assert len(docs) == 1
        doc = docs[0]
        assert isinstance(doc, SlimDocument)
        assert doc.id == "1"


def test_poll_source(
    setup_connector: PaperlessNgxConnector, mock_get_side_effect: Any
) -> None:
    with patch("requests.get") as mock_get:
        mock_get.side_effect = mock_get_side_effect

        since = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp())
        til = int(datetime(2023, 2, 1, tzinfo=timezone.utc).timestamp())
        docs = next(setup_connector.poll_source(since, til))

        assert len(docs) == 1
        doc = docs[0]
        assert doc.id == "1"
        assert doc.title == "Test Document"

        # Verify the date parameters were passed correctly
        calls = mock_get.call_args_list
        docs_call = [call for call in calls if DOCUMENTS_ENDPOINT in call[0][0]][0]
        expected_params = {
            "modified__gte": f"{datetime.fromtimestamp(since, timezone.utc).isoformat()}",
            "modified__lte": f"{datetime.fromtimestamp(til, timezone.utc).isoformat()}",
            "limit": DOC_BATCH_SIZE,
        }
        assert docs_call[1]["params"] == expected_params


def test_request_error_handling(setup_connector: PaperlessNgxConnector) -> None:
    with patch("requests.get") as mock_get:
        mock_get.side_effect = requests.exceptions.RequestException("Test error")

        with pytest.raises(CredentialInvalidError) as exc_info:
            setup_connector.validate_connector_settings()

        assert "Failed to connect" in str(exc_info.value)
        assert "Test error" in str(exc_info.value)
