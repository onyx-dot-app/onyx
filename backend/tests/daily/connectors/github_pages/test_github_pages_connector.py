import time
from unittest.mock import MagicMock
from unittest.mock import patch
from urllib.parse import urljoin

import pytest
import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.github_pages.connector import GitHubPagesConnector
from onyx.connectors.models import Document


@pytest.fixture
def github_pages_connector() -> GitHubPagesConnector:
    connector = GitHubPagesConnector(base_url="https://test.github.io", batch_size=10)
    connector.load_credentials(
        {
            "github_username": "test_user",
            "github_personal_access_token": "test_token",
        }
    )
    return connector


def test_normalize_url(github_pages_connector: GitHubPagesConnector):
    url = "https://test.github.io/page?query=abc#fragment"
    normalized = github_pages_connector._normalize_url(url)
    assert normalized == "https://test.github.io/page"


@patch("onyx.connectors.github_pages.connector.requests.get")
def test_fetch_with_retry_success(
    mock_get: MagicMock, github_pages_connector: GitHubPagesConnector
):
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.text = "<html>Test page</html>"
    fake_response.raise_for_status.return_value = None
    mock_get.return_value = fake_response

    result = github_pages_connector._fetch_with_retry("https://test.github.io/")
    assert result is not None
    assert "Test page" in result


@patch("onyx.connectors.github_pages.connector.requests.get")
def test_fetch_with_retry_failure(
    mock_get: MagicMock, github_pages_connector: GitHubPagesConnector
):
    fake_response = MagicMock()
    fake_response.status_code = 404
    fake_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "Not Found"
    )
    mock_get.return_value = fake_response

    result = github_pages_connector._fetch_with_retry(
        "https://test.github.io/nonexistent"
    )
    assert result is None


@patch("onyx.connectors.github_pages.connector.requests.get")
def test_crawl_github_pages(
    mock_get: MagicMock, github_pages_connector: GitHubPagesConnector
):
    base_page_html = "<html><body><a href='/page2'>Link to Page 2</a></body></html>"
    page2_html = "<html><body><p>Content of Page 2</p></body></html>"

    def fake_get(url, timeout, auth):
        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        if url.startswith(urljoin("https://test.github.io", "/page2")):
            fake_resp.status_code = 200
            fake_resp.text = page2_html
        else:
            fake_resp.status_code = 200
            fake_resp.text = base_page_html
        return fake_resp

    mock_get.side_effect = fake_get

    crawled_urls = github_pages_connector._crawl_github_pages(
        "https://test.github.io", batch_size=10
    )
    assert (
        "https://test.github.io" in crawled_urls
        or "https://test.github.io/" in crawled_urls
    )
    assert urljoin("https://test.github.io", "page2") in crawled_urls


@patch("onyx.connectors.github_pages.connector.requests.get")
def test_index_pages(mock_get: MagicMock, github_pages_connector: GitHubPagesConnector):
    base_page_html = "<html><body><h1>Base Page</h1></body></html>"
    page2_html = "<html><body><h1>Page 2</h1></body></html>"

    def fake_get(url, timeout, auth):
        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        if url.endswith("/page2"):
            fake_resp.status_code = 200
            fake_resp.text = page2_html
        else:
            fake_resp.status_code = 200
            fake_resp.text = base_page_html
        return fake_resp

    mock_get.side_effect = fake_get

    urls = ["https://test.github.io", urljoin("https://test.github.io", "page2")]
    documents = github_pages_connector._index_pages(urls)
    assert len(documents) == 2
    for doc in documents:
        assert isinstance(doc, Document)
        assert doc.source == DocumentSource.GITHUB_PAGES
        # The semantic_identifier here is the URL used to fetch the document.
        assert doc.semantic_identifier in urls


def test_load_from_state(github_pages_connector: GitHubPagesConnector):
    state = {"visited_urls": ["https://test.github.io", "https://test.github.io/page2"]}
    github_pages_connector.load_from_state(state)
    assert "https://test.github.io" in github_pages_connector.visited_urls
    assert "https://test.github.io/page2" in github_pages_connector.visited_urls


@patch("onyx.connectors.github_pages.connector.requests.get")
def test_poll_source(mock_get: MagicMock, github_pages_connector: GitHubPagesConnector):
    base_page_html = "<html><body><a href='/page2'>Link to Page 2</a></body></html>"
    page2_html = "<html><body><p>Content of Page 2</p></body></html>"

    def fake_get(url, timeout, auth):
        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        if url.startswith(urljoin("https://test.github.io", "/page2")):
            fake_resp.status_code = 200
            fake_resp.text = page2_html
        else:
            fake_resp.status_code = 200
            fake_resp.text = base_page_html
        return fake_resp

    mock_get.side_effect = fake_get

    generator = github_pages_connector.poll_source(0, time.time())
    batch = next(generator)
    assert isinstance(batch, list)
    assert len(batch) >= 2
    for doc in batch:
        assert isinstance(doc, Document)
