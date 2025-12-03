"""Unit tests for Azure DevOps connector.

These tests use mocks to validate connector logic without requiring
actual Azure DevOps credentials or network access.
"""

from datetime import datetime
from typing import Any
from unittest.mock import patch

import pytest


class MockGitRepository:
    """Mock Azure DevOps Git Repository."""

    def __init__(
        self, id: str, name: str, web_url: str, default_branch: str = "refs/heads/main"
    ):
        self.id = id
        self.name = name
        self.web_url = web_url
        self.default_branch = default_branch


class MockGitItem:
    """Mock Azure DevOps Git Item (file)."""

    def __init__(self, path: str, git_object_type: str = "blob", content: str = ""):
        self.path = path
        self.git_object_type = git_object_type
        self.content = content


class MockIdentityRef:
    """Mock Azure DevOps Identity Reference."""

    def __init__(self, display_name: str, unique_name: str = ""):
        self.display_name = display_name
        self.unique_name = (
            unique_name or f"{display_name.lower().replace(' ', '.')}@example.com"
        )


class MockGitPullRequest:
    """Mock Azure DevOps Pull Request."""

    def __init__(
        self,
        pull_request_id: int,
        title: str,
        description: str,
        status: str,
        created_by: MockIdentityRef,
        creation_date: datetime,
        repository: MockGitRepository,
    ):
        self.pull_request_id = pull_request_id
        self.title = title
        self.description = description
        self.status = status
        self.created_by = created_by
        self.creation_date = creation_date
        self.closed_date = None
        self.repository = repository
        self.source_ref_name = "refs/heads/feature-branch"
        self.target_ref_name = "refs/heads/main"
        self.merge_status = "succeeded"
        self.reviewers = []


class TestAzureDevOpsConnectorInit:
    """Test connector initialization and configuration."""

    def test_connector_instantiation(self) -> None:
        """Test that the connector can be instantiated with valid config."""
        with patch("onyx.connectors.azure_devops.connector.Connection"):
            from onyx.connectors.azure_devops.connector import AzureDevOpsConnector

            connector = AzureDevOpsConnector(
                organization="test-org",
                project="test-project",
                repositories="repo1,repo2",
                include_code_files=True,
                include_prs=True,
            )

            assert connector.organization == "test-org"
            assert connector.project == "test-project"
            # repositories is stored as a string, not parsed
            assert connector.repositories == "repo1,repo2"
            assert connector.include_code_files is True
            assert connector.include_prs is True

    def test_connector_default_values(self) -> None:
        """Test connector default configuration values."""
        with patch("onyx.connectors.azure_devops.connector.Connection"):
            from onyx.connectors.azure_devops.connector import AzureDevOpsConnector

            connector = AzureDevOpsConnector(
                organization="test-org",
                project="test-project",
            )

            assert connector.repositories is None
            assert connector.include_code_files is True
            assert connector.include_prs is True

    def test_connector_empty_repositories(self) -> None:
        """Test connector with empty repositories string."""
        with patch("onyx.connectors.azure_devops.connector.Connection"):
            from onyx.connectors.azure_devops.connector import AzureDevOpsConnector

            connector = AzureDevOpsConnector(
                organization="test-org",
                project="test-project",
                repositories="",
            )

            # Empty string is stored as-is
            assert connector.repositories == ""


class TestAzureDevOpsConnectorCredentials:
    """Test credential loading."""

    def test_load_credentials(self) -> None:
        """Test loading PAT credentials."""
        with patch("onyx.connectors.azure_devops.connector.Connection") as mock_conn:
            from onyx.connectors.azure_devops.connector import AzureDevOpsConnector

            connector = AzureDevOpsConnector(
                organization="test-org",
                project="test-project",
            )

            credentials = {"azure_devops_pat": "test-pat-token"}
            result = connector.load_credentials(credentials)

            assert result is None  # Should return None on success
            # Verify Connection was created with correct URL
            mock_conn.assert_called_once()
            call_args = mock_conn.call_args
            assert "https://dev.azure.com/test-org" in str(call_args)


class TestAzureDevOpsDocumentConversion:
    """Test document conversion functions."""

    @pytest.fixture
    def mock_repository(self) -> MockGitRepository:
        """Create a mock repository."""
        return MockGitRepository(
            id="repo-123",
            name="test-repo",
            web_url="https://dev.azure.com/test-org/test-project/_git/test-repo",
        )

    @pytest.fixture
    def mock_pull_request(
        self, mock_repository: MockGitRepository
    ) -> MockGitPullRequest:
        """Create a mock pull request."""
        return MockGitPullRequest(
            pull_request_id=42,
            title="Add new feature",
            description="This PR adds a new feature to the application.",
            status="active",
            created_by=MockIdentityRef("John Doe"),
            creation_date=datetime(2025, 1, 15, 10, 30, 0),
            repository=mock_repository,
        )

    @pytest.fixture
    def mock_git_item(self) -> MockGitItem:
        """Create a mock git item (file)."""
        return MockGitItem(
            path="/src/main.py",
            git_object_type="blob",
        )

    def test_convert_pr_to_document(
        self, mock_pull_request: MockGitPullRequest
    ) -> None:
        """Test converting a PR to a Document."""
        from onyx.configs.constants import DocumentSource
        from onyx.connectors.azure_devops.connector import _convert_pr_to_document

        doc = _convert_pr_to_document(
            pr=mock_pull_request,
            organization="test-org",
            project="test-project",
            repo_name="test-repo",
        )

        assert doc is not None
        assert doc.source == DocumentSource.AZURE_DEVOPS
        assert "42" in doc.id
        assert doc.metadata["object_type"] == "PullRequest"
        assert doc.metadata["id"] == "42"
        assert doc.metadata["status"] == "active"
        assert doc.metadata["repo"] == "test-repo"
        assert len(doc.sections) == 1
        assert "This PR adds" in doc.sections[0].text

    def test_convert_code_file_to_document(self, mock_git_item: MockGitItem) -> None:
        """Test converting a code file to a Document."""
        from onyx.configs.constants import DocumentSource
        from onyx.connectors.azure_devops.connector import (
            _convert_code_file_to_document,
        )

        file_content = "def hello():\n    print('Hello, World!')"

        doc = _convert_code_file_to_document(
            item=mock_git_item,
            content=file_content,
            organization="test-org",
            project="test-project",
            repo_name="test-repo",
            default_branch="main",
        )

        assert doc is not None
        assert doc.source == DocumentSource.AZURE_DEVOPS
        assert "main.py" in doc.semantic_identifier
        assert doc.metadata["object_type"] == "CodeFile"
        assert doc.metadata["file_path"] == "src/main.py"
        assert doc.metadata["repo"] == "test-repo"
        assert len(doc.sections) == 1
        assert "def hello():" in doc.sections[0].text

    def test_convert_code_file_with_commit_date(
        self, mock_git_item: MockGitItem
    ) -> None:
        """Test converting a code file with explicit commit date."""
        from datetime import timezone

        from onyx.configs.constants import DocumentSource
        from onyx.connectors.azure_devops.connector import (
            _convert_code_file_to_document,
        )

        file_content = "# Test file"
        commit_date = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

        doc = _convert_code_file_to_document(
            item=mock_git_item,
            content=file_content,
            organization="test-org",
            project="test-project",
            repo_name="test-repo",
            default_branch="main",
            commit_date=commit_date,
        )

        assert doc is not None
        assert doc.source == DocumentSource.AZURE_DEVOPS
        assert doc.doc_updated_at == commit_date


class TestAzureDevOpsFileFiltering:
    """Test file extension filtering."""

    def test_should_index_file(self) -> None:
        """Test that supported file types are correctly identified."""
        from onyx.connectors.azure_devops.connector import _should_index_file

        # These should be indexed
        assert _should_index_file("/src/main.py") is True
        assert _should_index_file("/app/component.tsx") is True
        assert _should_index_file("/README.md") is True
        assert _should_index_file("/config.yaml") is True

        # These should NOT be indexed
        assert _should_index_file("/node_modules/package/index.js") is False
        assert _should_index_file("/.git/config") is False
        assert _should_index_file("/image.png") is False

    def test_should_exclude(self) -> None:
        """Test that exclusion patterns work correctly."""
        from onyx.connectors.azure_devops.connector import _should_exclude

        assert _should_exclude("node_modules/") is True
        assert _should_exclude(".git/") is True
        assert _should_exclude("package-lock.json") is True
        assert _should_exclude("src/main.py") is False


class TestAzureDevOpsConnectorCheckpoint:
    """Test checkpoint functionality."""

    def test_build_dummy_checkpoint(self) -> None:
        """Test building initial checkpoint."""
        with patch("onyx.connectors.azure_devops.connector.Connection"):
            from onyx.connectors.azure_devops.connector import AzureDevOpsConnector

            connector = AzureDevOpsConnector(
                organization="test-org",
                project="test-project",
            )

            checkpoint = connector.build_dummy_checkpoint()

            assert checkpoint is not None
            assert checkpoint.has_more is True
