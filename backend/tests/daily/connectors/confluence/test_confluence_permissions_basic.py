import os

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.confluence.connector import ConfluenceConnector
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider


@pytest.fixture
def confluence_connector() -> ConfluenceConnector:
    connector = ConfluenceConnector(
        wiki_base="https://danswerai.atlassian.net",
        is_cloud=True,
    )

    credentials_provider = OnyxStaticCredentialsProvider(
        None,
        DocumentSource.CONFLUENCE,
        {
            "confluence_username": os.environ["CONFLUENCE_USER_NAME"],
            "confluence_access_token": os.environ["CONFLUENCE_ACCESS_TOKEN"],
        },
    )
    connector.set_credentials_provider(credentials_provider)
    return connector


# This should never fail because even if the docs in the cloud change,
# the full doc ids retrieved should always be a subset of the slim doc ids
@pytest.mark.skip(reason="Skipping this test")
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

    # Find IDs that are in full but not in slim
    difference = all_full_doc_ids - all_slim_doc_ids

    # The set of full doc IDs should be always be a subset of the slim doc IDs
    assert all_full_doc_ids.issubset(
        all_slim_doc_ids
    ), f"Full doc IDs are not a subset of slim doc IDs. Found {len(difference)} IDs in full docs but not in slim docs."
