import pytest
from unittest.mock import MagicMock, patch
from danswer.connectors.github_pages.connector import GithubPagesConnector


@pytest.fixture
def github_pages_connector() -> GithubPagesConnector:
    connector = GithubPagesConnector(base_url="https://test.github.io")
    connector.load_credentials(
        {"github_username": "test_user", "github_personal_access_token": "test_token"}
    )
    return connector


@patch("requests.get")
def test_github_pages_connector_basic(mock_get: MagicMock, github_pages_connector: GithubPagesConnector):
    mock_get.side_effect = [
        MagicMock(status_code=200, text="<html><a href='/page2'>Link to Page 2</a></html>"),
        MagicMock(status_code=200, text="<html>Content of Page 2</html>"),
    ]

    doc_batch_generator = github_pages_connector.poll_source(0, time.time())
    doc_batch = next(doc_batch_generator)

    assert len(doc_batch) == 2  
    assert doc_batch[0].semantic_identifier.startswith("https://test.github.io")  
