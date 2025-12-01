import os
import time
from pathlib import Path

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.azure_devops.connector import AzureDevOpsConnector
from tests.daily.connectors.utils import load_all_docs_from_checkpoint_connector


@pytest.fixture(autouse=True)
def load_env_file() -> None:
    """Autouse fixture to load `.env` in this tests directory into os.environ.

    This mirrors the one-off wrapper we used in the terminal but keeps the
    behavior self-contained in the tests. Missing `.env` is silently ignored
    so CI can skip these tests when not configured.
    """
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if key:
            os.environ.setdefault(key, val)


@pytest.fixture
def azure_devops_connector() -> AzureDevOpsConnector:
    """Daily fixture for Azure DevOps connector.

    Env vars:
    - AZURE_DEVOPS_PAT: Azure DevOps Personal Access Token
    - AZURE_DEVOPS_ORGANIZATION: Azure DevOps organization name
    - AZURE_DEVOPS_PROJECT: Azure DevOps project name
    - AZURE_DEVOPS_REPOSITORIES: optional comma-separated repository names
    """
    organization = os.environ.get("AZURE_DEVOPS_ORGANIZATION")
    project = os.environ.get("AZURE_DEVOPS_PROJECT")
    repositories = os.environ.get("AZURE_DEVOPS_REPOSITORIES")
    pat = os.environ.get("AZURE_DEVOPS_PAT")

    if not organization or not project:
        pytest.skip(
            "AZURE_DEVOPS_ORGANIZATION or AZURE_DEVOPS_PROJECT not set in environment"
        )

    if not pat:
        pytest.skip("AZURE_DEVOPS_PAT not set in environment")

    connector = AzureDevOpsConnector(
        organization=organization,
        project=project,
        repositories=repositories,
        include_code_files=True,
        include_prs=True,
    )

    connector.load_credentials({"azure_devops_pat": pat})
    return connector


@pytest.fixture
def azure_devops_connector_code_only() -> AzureDevOpsConnector:
    """Fixture for testing code files only."""
    organization = os.environ.get("AZURE_DEVOPS_ORGANIZATION")
    project = os.environ.get("AZURE_DEVOPS_PROJECT")
    repositories = os.environ.get("AZURE_DEVOPS_REPOSITORIES")
    pat = os.environ.get("AZURE_DEVOPS_PAT")

    if not organization or not project:
        pytest.skip(
            "AZURE_DEVOPS_ORGANIZATION or AZURE_DEVOPS_PROJECT not set in environment"
        )

    if not pat:
        pytest.skip("AZURE_DEVOPS_PAT not set in environment")

    connector = AzureDevOpsConnector(
        organization=organization,
        project=project,
        repositories=repositories,
        include_code_files=True,
        include_prs=False,
    )

    connector.load_credentials({"azure_devops_pat": pat})
    return connector


@pytest.fixture
def azure_devops_connector_prs_only() -> AzureDevOpsConnector:
    """Fixture for testing pull requests only."""
    organization = os.environ.get("AZURE_DEVOPS_ORGANIZATION")
    project = os.environ.get("AZURE_DEVOPS_PROJECT")
    repositories = os.environ.get("AZURE_DEVOPS_REPOSITORIES")
    pat = os.environ.get("AZURE_DEVOPS_PAT")

    if not organization or not project:
        pytest.skip(
            "AZURE_DEVOPS_ORGANIZATION or AZURE_DEVOPS_PROJECT not set in environment"
        )

    if not pat:
        pytest.skip("AZURE_DEVOPS_PAT not set in environment")

    connector = AzureDevOpsConnector(
        organization=organization,
        project=project,
        repositories=repositories,
        include_code_files=False,
        include_prs=True,
    )

    connector.load_credentials({"azure_devops_pat": pat})
    return connector


def test_azure_devops_connector_basic(
    azure_devops_connector: AzureDevOpsConnector,
) -> None:
    """Test basic Azure DevOps connector functionality."""
    docs = load_all_docs_from_checkpoint_connector(
        connector=azure_devops_connector,
        start=0,
        end=time.time(),
    )

    # We expect at least some documents (code files or PRs)
    assert isinstance(docs, list)

    # If there are documents, verify their structure
    for doc in docs:
        # Verify basic document properties
        assert doc.source == DocumentSource.AZURE_DEVOPS
        assert doc.secondary_owners is None
        assert doc.from_ingestion_api is False
        assert doc.additional_info is None

        # Verify metadata
        assert doc.metadata is not None
        object_type = doc.metadata.get("object_type")
        assert object_type in ("CodeFile", "PullRequest")

        # Verify sections
        assert len(doc.sections) >= 1
        section = doc.sections[0]
        assert isinstance(section.link, str)
        assert isinstance(section.text, str)

        # Verify Azure DevOps-specific URL in section link
        assert "dev.azure.com" in section.link or "visualstudio.com" in section.link


def test_azure_devops_code_files(
    azure_devops_connector_code_only: AzureDevOpsConnector,
) -> None:
    """Test Azure DevOps connector for code files only."""
    docs = load_all_docs_from_checkpoint_connector(
        connector=azure_devops_connector_code_only,
        start=0,
        end=time.time(),
    )

    assert isinstance(docs, list)

    # All docs should be code files
    for doc in docs:
        assert doc.source == DocumentSource.AZURE_DEVOPS
        assert doc.metadata is not None
        assert doc.metadata.get("object_type") == "CodeFile"
        assert "file_path" in doc.metadata
        assert "repo" in doc.metadata

        # Verify sections contain code content
        assert len(doc.sections) >= 1
        section = doc.sections[0]
        assert isinstance(section.text, str)


def test_azure_devops_pull_requests(
    azure_devops_connector_prs_only: AzureDevOpsConnector,
) -> None:
    """Test Azure DevOps connector for pull requests only."""
    docs = load_all_docs_from_checkpoint_connector(
        connector=azure_devops_connector_prs_only,
        start=0,
        end=time.time(),
    )

    assert isinstance(docs, list)

    # All docs should be pull requests
    for doc in docs:
        assert doc.source == DocumentSource.AZURE_DEVOPS
        assert doc.metadata is not None
        assert doc.metadata.get("object_type") == "PullRequest"

        # Verify PR-specific metadata
        assert "id" in doc.metadata
        assert "status" in doc.metadata
        assert "repo" in doc.metadata

        # Title is in semantic_identifier, creator in primary_owners
        assert doc.semantic_identifier is not None

        # Verify sections
        assert len(doc.sections) >= 1
        section = doc.sections[0]
        assert isinstance(section.text, str)


def test_azure_devops_connector_structure(
    azure_devops_connector: AzureDevOpsConnector,
) -> None:
    """Test that the connector class has required methods and properties."""
    # Check connector has required methods
    assert hasattr(azure_devops_connector, "load_credentials")
    assert hasattr(azure_devops_connector, "load_from_checkpoint")
    assert hasattr(azure_devops_connector, "build_dummy_checkpoint")

    # Check connector can build checkpoint
    checkpoint = azure_devops_connector.build_dummy_checkpoint()
    assert checkpoint is not None
    assert hasattr(checkpoint, "has_more")
