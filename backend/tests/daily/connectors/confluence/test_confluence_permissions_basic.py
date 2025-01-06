import os

import pytest

from onyx.connectors.confluence.connector import ConfluenceConnector


@pytest.fixture
def confluence_connector() -> ConfluenceConnector:
    connector = ConfluenceConnector(
        wiki_base="https://danswerai.atlassian.net",
        is_cloud=True,
    )
    connector.load_credentials(
        {
            "confluence_access_token": os.environ["CONFLUENCE_ACCESS_TOKEN"],
            "confluence_username": os.environ["CONFLUENCE_USER_NAME"],
        }
    )
    return connector


# This should never fail because even if the docs in the cloud change,
# the full doc ids retrieved should always be a subset of the slim doc ids
def test_confluence_connector_permissions(
    confluence_connector: ConfluenceConnector,
) -> None:
    # Get all doc IDs from the full connector
    all_full_doc_ids = set()
    for doc_batch in confluence_connector.load_from_state():
        all_full_doc_ids.update([doc.id for doc in doc_batch])

    # Get all doc IDs from the slim connector
    all_slim_doc_ids = set()
    for slim_doc_batch in confluence_connector.retrieve_all_slim_documents():
        all_slim_doc_ids.update([doc.id for doc in slim_doc_batch])

    # The set of full doc IDs should be always be a subset of the slim doc IDs
    assert all_full_doc_ids.issubset(all_slim_doc_ids)
