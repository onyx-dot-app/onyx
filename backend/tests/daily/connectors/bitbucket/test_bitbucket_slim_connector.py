import os
import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.bitbucket.connector import BitbucketConnector
from tests.daily.connectors.utils import load_all_docs_from_checkpoint_connector


@pytest.fixture
def bitbucket_connector_for_slim() -> BitbucketConnector:
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


def test_bitbucket_full_ids_subset_of_slim_ids(
    bitbucket_connector_for_slim: BitbucketConnector,
) -> None:
    # Get all full doc IDs from load_from_state
    docs = load_all_docs_from_checkpoint_connector(
        connector=bitbucket_connector_for_slim,
        start=0,
        end=time.time(),
    )
    all_full_doc_ids: set[str] = set([doc.id for doc in docs])

    # Get all doc IDs from the slim connector
    all_slim_doc_ids: set[str] = set()
    for (
        slim_doc_batch
    ) in bitbucket_connector_for_slim.retrieve_all_slim_docs_perm_sync():
        all_slim_doc_ids.update([doc.id for doc in slim_doc_batch])

    # The set of full doc IDs should always be a subset of slim doc IDs
    assert all_full_doc_ids.issubset(all_slim_doc_ids)
    # Make sure we actually got some documents
    assert len(all_slim_doc_ids) > 0

    # Basic sanity checks if any docs exist
    if all_slim_doc_ids:
        example_id = next(iter(all_slim_doc_ids))
        assert example_id.startswith(f"{DocumentSource.BITBUCKET.value}:")
