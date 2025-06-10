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
    assert len(docs) > 1  # We expect at least one PR and one Issue to exist

    # Test the first document's structure
    pr_doc = docs[0]
    issue_doc = docs[-1]

    # Verify basic document properties
    assert pr_doc.source == DocumentSource.GITHUB
    assert pr_doc.secondary_owners is None
    assert pr_doc.from_ingestion_api is False
    assert pr_doc.additional_info is None

    # Verify GitHub-specific properties
    assert "github.com" in pr_doc.id  # Should be a GitHub URL

    # Verify PR-specific properties
    assert pr_doc.metadata is not None
    assert pr_doc.metadata.get("object_type") == "PullRequest"
    assert "id" in pr_doc.metadata
    assert "merged" in pr_doc.metadata
    assert "state" in pr_doc.metadata
    assert "user" in pr_doc.metadata
    assert "assignees" in pr_doc.metadata
    assert pr_doc.metadata.get("repo") == "onyx-dot-app/documentation"
    assert "num_commits" in pr_doc.metadata
    assert "num_files_changed" in pr_doc.metadata
    assert "labels" in pr_doc.metadata
    assert "created_at" in pr_doc.metadata

    # Verify Issue-specific properties
    assert issue_doc.metadata is not None
    assert issue_doc.metadata.get("object_type") == "Issue"
    assert "id" in issue_doc.metadata
    assert "state" in issue_doc.metadata
    assert "user" in issue_doc.metadata
    assert "assignees" in issue_doc.metadata
    assert issue_doc.metadata.get("repo") == "onyx-dot-app/documentation"
    assert "labels" in issue_doc.metadata
    assert "created_at" in issue_doc.metadata

    # Verify sections
    assert len(pr_doc.sections) == 1
    section = pr_doc.sections[0]
    assert section.link == pr_doc.id  # Section link should match document ID
    assert isinstance(section.text, str)  # Should have some text content
