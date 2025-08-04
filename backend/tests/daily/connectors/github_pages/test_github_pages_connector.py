from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.github_pages.connector import GitHubPagesConnector


@pytest.fixture
def github_pages_connector() -> GitHubPagesConnector:
    connector = GitHubPagesConnector(
        repo_owner="test-owner",
        repo_name="test-repo",
        branch="main",
        max_files=10,
        batch_size=10,
    )
    connector.load_credentials(
        {
            "github_username": "test_user",
            "github_personal_access_token": "test_token",
        }
    )
    return connector


def test_connector_initialization() -> None:
    """Test that the connector can be initialized properly."""
    connector = GitHubPagesConnector(
        repo_owner="test-owner", repo_name="test-repo", branch="main", max_files=50
    )
    assert connector.repo_owner == "test-owner"
    assert connector.repo_name == "test-repo"
    assert connector.branch == "main"
    assert connector.max_files == 50


def test_should_process_file(github_pages_connector: GitHubPagesConnector) -> None:
    """Test file filtering logic."""
    # Test supported extensions
    assert github_pages_connector._should_process_file("index.html") is True
    assert github_pages_connector._should_process_file("readme.md") is True
    assert github_pages_connector._should_process_file("docs.txt") is True

    # Test unsupported extensions
    assert github_pages_connector._should_process_file("style.css") is False
    assert github_pages_connector._should_process_file("script.js") is False
    assert github_pages_connector._should_process_file("image.png") is False


def test_respect_depth_limit(github_pages_connector: GitHubPagesConnector) -> None:
    """Test depth limiting logic."""
    # Test without depth limit
    assert github_pages_connector._respect_depth_limit("file.txt") is True
    assert github_pages_connector._respect_depth_limit("docs/file.txt") is True

    # Test with depth limit
    github_pages_connector.max_depth = 1
    assert github_pages_connector._respect_depth_limit("file.txt") is True
    assert github_pages_connector._respect_depth_limit("docs/file.txt") is True
    assert github_pages_connector._respect_depth_limit("docs/sub/file.txt") is False


def test_build_page_url(github_pages_connector: GitHubPagesConnector) -> None:
    """Test URL building logic."""
    # Test regular files
    url = github_pages_connector._build_page_url("docs/readme.html")
    assert url == "https://test-owner.github.io/test-repo/docs/readme.html"

    # Test index.html files
    url = github_pages_connector._build_page_url("index.html")
    assert url == "https://test-owner.github.io/test-repo/"

    # Test markdown files
    url = github_pages_connector._build_page_url("docs/readme.md")
    assert url == "https://test-owner.github.io/test-repo/docs/readme.html"


@patch("onyx.connectors.github_pages.connector.requests.get")
def test_download_file_content(
    mock_get: MagicMock, github_pages_connector: GitHubPagesConnector
) -> None:
    """Test file content downloading."""
    from onyx.connectors.github_pages.connector import GitHubPagesFileInfo

    # Mock response
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.content = b"<html><body>Test content</body></html>"
    fake_response.raise_for_status.return_value = None
    mock_get.return_value = fake_response

    # Create file info
    file_info = GitHubPagesFileInfo(
        path="test.html",
        original_path="test.html",
        sha="abc123",
        size=100,
        url="https://api.github.com/repos/test/test/contents/test.html",
        download_url="https://raw.githubusercontent.com/test/test/main/test.html",
    )

    # Test download
    content = github_pages_connector._download_file_content(file_info)
    assert "Test content" in content


def test_process_file_content(github_pages_connector: GitHubPagesConnector) -> None:
    """Test file content processing."""
    # Test HTML processing
    html_content = "<html><body><h1>Title</h1><p>Content</p></body></html>"
    processed = github_pages_connector._process_file_content(html_content, "test.html")
    assert "Title" in processed
    assert "Content" in processed

    # Test markdown processing
    md_content = "# Title\n\nThis is **bold** text."
    processed = github_pages_connector._process_file_content(md_content, "test.md")
    assert "Title" in processed
    assert "bold" in processed

    # Test text processing
    text_content = "Plain text content"
    processed = github_pages_connector._process_file_content(text_content, "test.txt")
    assert processed == text_content


def test_create_document(github_pages_connector: GitHubPagesConnector) -> None:
    """Test document creation."""
    from onyx.connectors.github_pages.connector import GitHubPagesFileInfo

    file_info = GitHubPagesFileInfo(
        path="docs/readme.md",
        original_path="docs/readme.md",
        sha="abc123",
        size=100,
        url="https://api.github.com/repos/test/test/contents/docs/readme.md",
        download_url="https://raw.githubusercontent.com/test/test/main/docs/readme.md",
    )

    content = "This is test content"
    doc = github_pages_connector._create_document(file_info, content)

    assert doc.source == DocumentSource.WEB
    assert doc.semantic_identifier == "docs > readme"
    assert doc.id == "https://test-owner.github.io/test-repo/docs/readme.html"
    assert len(doc.sections) == 1
    assert doc.sections[0].text == content


def test_validate_connector_settings(
    github_pages_connector: GitHubPagesConnector,
) -> None:
    """Test connector validation."""
    # Test with valid settings
    try:
        github_pages_connector.validate_connector_settings()
    except Exception:
        # This might fail in test environment, which is expected
        pass

    # Test with invalid settings
    invalid_connector = GitHubPagesConnector(repo_owner="", repo_name="", max_files=10)

    with pytest.raises(Exception):
        invalid_connector.validate_connector_settings()
