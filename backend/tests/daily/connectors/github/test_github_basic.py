import os
import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.github.connector import GithubConnector
from tests.daily.connectors.utils import load_all_docs_from_checkpoint_connector


@pytest.fixture
def github_connector() -> GithubConnector:
    connector = GithubConnector(
        repo_owner="onyx-dot-app",
        repositories="documentation",
        include_prs=True,
        include_issues=True,
    )
    connector.load_credentials(
        {
            "github_access_token": os.environ["ACCESS_TOKEN_GITHUB"],
        }
    )
    return connector


def test_github_connector_basic(github_connector: GithubConnector) -> None:
    docs = load_all_docs_from_checkpoint_connector(
        connector=github_connector,
        start=0,
        end=time.time(),
    )
    assert len(docs) > 0  # We expect at least one PR to exist

    # Test the first document's structure
    doc = docs[0]

    # Verify basic document properties
    assert doc.source == DocumentSource.GITHUB
    assert doc.secondary_owners is None
    assert doc.from_ingestion_api is False
    assert doc.additional_info is None

    # Verify GitHub-specific properties
    assert "github.com" in doc.id  # Should be a GitHub URL
    assert doc.metadata is not None
    assert "state" in doc.metadata
    assert "merged" in doc.metadata

    # Verify sections
    assert len(doc.sections) == 1
    section = doc.sections[0]
    assert section.link == doc.id  # Section link should match document ID
    assert isinstance(section.text, str)  # Should have some text content
