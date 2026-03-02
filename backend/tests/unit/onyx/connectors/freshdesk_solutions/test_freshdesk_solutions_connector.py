from unittest.mock import Mock
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.freshdesk_solutions.connector import _create_doc_from_article
from onyx.connectors.freshdesk_solutions.connector import FreshdeskSolutionsConnector
from onyx.connectors.models import ConnectorMissingCredentialError


def test_load_credentials_normalizes_domain() -> None:
    connector = FreshdeskSolutionsConnector()
    connector.load_credentials(
        {
            "freshdesk_solution_api_key": "key",
            "freshdesk_solution_domain": "https://Acme.Freshdesk.com/",
            "freshdesk_solution_password": "x",
        }
    )

    assert connector.domain == "acme"
    assert connector.api_key == "key"
    assert connector.password == "x"


def test_load_credentials_requires_all_fields() -> None:
    connector = FreshdeskSolutionsConnector()
    with pytest.raises(ConnectorMissingCredentialError):
        connector.load_credentials(
            {
                "freshdesk_solution_api_key": "key",
                "freshdesk_solution_domain": "acme",
            }
        )


def test_create_doc_from_article_without_images() -> None:
    connector = FreshdeskSolutionsConnector()

    category = {"name": "General"}
    folder = {"name": "FAQ"}
    article = {
        "id": 42,
        "title": "Reset password",
        "description": "<p>How to reset password</p>",
        "description_text": "How to reset password",
        "updated_at": "2025-01-01T00:00:00Z",
        "created_at": "2025-01-01T00:00:00Z",
        "agent_id": 9,
        "category_id": 1,
        "folder_id": 2,
        "tags": ["auth"],
    }

    with patch(
        "onyx.connectors.freshdesk_solutions.connector.get_image_extraction_and_analysis_enabled",
        return_value=False,
    ):
        docs = _create_doc_from_article(
            category=category,
            folder=folder,
            article=article,
            domain="acme",
            name="freshdesk_solutions",
            connector=connector,
        )

    assert len(docs) == 1
    doc = docs[0]
    assert doc.source == DocumentSource.FRESHDESK_SOLUTIONS
    assert doc.semantic_identifier == "Reset password"
    assert "Category: General" in doc.sections[0].text
    assert "Folder: FAQ" in doc.sections[0].text


def test_request_with_retries_retries_after_429() -> None:
    connector = FreshdeskSolutionsConnector()
    connector.api_key = "key"
    connector.password = "x"

    response_429 = Mock()
    response_429.status_code = 429
    response_429.headers = {"Retry-After": "0"}

    response_200 = Mock()
    response_200.status_code = 200
    response_200.headers = {}
    response_200.raise_for_status = Mock()

    with (
        patch(
            "onyx.connectors.freshdesk_solutions.connector.requests.get",
            side_effect=[response_429, response_200],
        ),
        patch("onyx.connectors.freshdesk_solutions.connector.time.sleep"),
    ):
        response = connector._request_with_retries("https://example.com")

    assert response is response_200
