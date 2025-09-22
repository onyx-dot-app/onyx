import os
import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.bitbucket.connector import BitbucketConnector
from tests.daily.connectors.utils import load_all_docs_from_checkpoint_connector


@pytest.fixture
def bitbucket_connector_for_checkpoint() -> BitbucketConnector:
    """Daily fixture for Bitbucket checkpointed indexing.

    Env vars:
    - BITBUCKET_EMAIL: Bitbucket account email
    - BITBUCKET_API_TOKEN: Bitbucket app password/token
    - BITBUCKET_WORKSPACE: workspace id
    - BITBUCKET_REPOSITORIES: comma-separated slugs
    - BITBUCKET_PROJECTS: optional comma-separated project keys
    """
    workspace = os.environ["BITBUCKET_WORKSPACE"]
    repositories = os.environ.get("BITBUCKET_REPOSITORIES")
    projects = os.environ.get("BITBUCKET_PROJECTS")

    connector = BitbucketConnector(
        workspace=workspace,
        repositories=repositories,
        projects=projects,
        batch_size=10,
    )

    email = os.environ.get("BITBUCKET_EMAIL")
    token = os.environ.get("BITBUCKET_API_TOKEN")
    if not email or not token:
        pytest.skip("BITBUCKET_EMAIL or BITBUCKET_API_TOKEN not set in environment")

    connector.load_credentials({"bitbucket_email": email, "bitbucket_api_token": token})
    return connector


def test_bitbucket_checkpointed_load(
    bitbucket_connector_for_checkpoint: BitbucketConnector,
) -> None:
    # Use a broad window; results may be empty depending on repository state
    start = 1755004439  # Tue Aug 12 2025 13:13:59 UTC
    end = time.time()

    docs = load_all_docs_from_checkpoint_connector(
        connector=bitbucket_connector_for_checkpoint,
        start=start,
        end=end,
    )

    assert isinstance(docs, list)

    for doc in docs:
        assert doc.source == DocumentSource.BITBUCKET
        assert doc.metadata is not None
        assert doc.metadata.get("object_type") == "PullRequest"
        assert "id" in doc.metadata
        assert "state" in doc.metadata
        assert "title" in doc.metadata
        assert "updated_on" in doc.metadata

        # Basic section checks
        assert len(doc.sections) >= 1
        section = doc.sections[0]
        assert isinstance(section.link, str)
        assert isinstance(section.text, str)
