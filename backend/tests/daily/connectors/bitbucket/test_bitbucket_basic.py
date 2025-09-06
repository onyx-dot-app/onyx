import itertools
import os
import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.bitbucket.connector import BitbucketConnector


@pytest.fixture
def bitbucket_connector() -> BitbucketConnector:
    """
    Daily test fixture for BitbucketConnector using a small public repo by default.

    Env vars:
    - BITBUCKET_EMAIL: Bitbucket account email
    - BITBUCKET_API_TOKEN: Bitbucket app password/token
    - BITBUCKET_WORKSPACE: workspace id
    - BITBUCKET_REPOSITORIES: comma-separated slugs
    - BITBUCKET_PROJECTS: optional comma-separated project keys
    """
    workspace = os.environ.get("BITBUCKET_WORKSPACE")
    repositories = os.environ.get("BITBUCKET_REPOSITORIES")
    projects = os.environ.get("BITBUCKET_PROJECTS")
    prune_days = -1

    connector = BitbucketConnector(
        workspace=workspace,
        repositories=repositories,
        projects=projects,
        batch_size=10,
        prune_closed_prs_after_days=prune_days,
    )

    email = os.environ.get("BITBUCKET_EMAIL")
    token = os.environ.get("BITBUCKET_API_TOKEN")
    if not email or not token:
        pytest.skip("BITBUCKET_EMAIL or BITBUCKET_API_TOKEN not set in environment")

    connector.load_credentials({"bitbucket_email": email, "bitbucket_api_token": token})
    return connector


def test_bitbucket_load_from_state(bitbucket_connector: BitbucketConnector) -> None:
    batches = bitbucket_connector.load_from_state()
    docs = list(itertools.chain(*batches))

    # We expect at least zero or more PRs depending on repository state
    assert isinstance(docs, list)

    for doc in docs:
        assert doc.source == DocumentSource.BITBUCKET
        assert doc.metadata is not None
        assert doc.metadata.get("object_type") == "PullRequest"
        assert "id" in doc.metadata
        assert "state" in doc.metadata
        assert "title" in doc.metadata
        assert "created_on" in doc.metadata
        assert "updated_on" in doc.metadata

        # Basic section checks
        assert len(doc.sections) >= 1
        section = doc.sections[0]
        assert isinstance(section.link, str)
        assert isinstance(section.text, str)


def test_bitbucket_poll_source(bitbucket_connector: BitbucketConnector) -> None:
    current = time.time()
    specific_date = 1755004439  # Tue Aug 12 2025 13:13:59 UTC
    batches = bitbucket_connector.poll_source(specific_date, current)
    docs = list(itertools.chain(*batches))

    # Validate structure; results may be empty depending on recent activity
    assert isinstance(docs, list)
    for doc in docs:
        assert doc.source == DocumentSource.BITBUCKET
        assert doc.metadata is not None
        assert doc.metadata.get("object_type") == "PullRequest"
        assert "id" in doc.metadata
        assert "state" in doc.metadata
        assert "title" in doc.metadata
        assert "updated_on" in doc.metadata


def test_bitbucket_slim_documents(bitbucket_connector: BitbucketConnector) -> None:
    batches = bitbucket_connector.retrieve_all_slim_documents()
    ids = list(itertools.chain(*batches))

    # Slim docs are ids only; may be empty depending on repo
    assert isinstance(ids, list)
    for slim in ids:
        assert isinstance(slim.id, str)
        assert slim.id.startswith(f"{DocumentSource.BITBUCKET.value}:")
