import os
import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.pylon.connector import PylonConnector
from tests.daily.connectors.utils import load_all_docs_from_checkpoint_connector


@pytest.fixture
def pylon_connector_for_slim() -> PylonConnector:
    api_key = os.environ.get("PYLON_API_KEY")

    if not api_key:
        pytest.skip("PYLON_API_KEY not set in environment")

    connector = PylonConnector(
        pylon_entities=["messages"],  # issues always included
        start_date="2025-10-16",
        lookback_days=0,
        batch_size=10,
    )

    connector.load_credentials({"pylon_api_key": api_key})
    return connector


def test_pylon_full_ids_subset_of_slim_ids(
    pylon_connector_for_slim: PylonConnector,
) -> None:
    docs = load_all_docs_from_checkpoint_connector(
        connector=pylon_connector_for_slim,
        start=0,
        end=time.time(),
    )
    all_full_doc_ids: set[str] = set([doc.id for doc in docs])

    all_slim_doc_ids: set[str] = set()
    for slim_doc_batch in pylon_connector_for_slim.retrieve_all_slim_docs_perm_sync():
        all_slim_doc_ids.update([doc.id for doc in slim_doc_batch])

    assert all_full_doc_ids.issubset(all_slim_doc_ids)
    assert len(all_slim_doc_ids) > 0

    if all_slim_doc_ids:
        example_id = next(iter(all_slim_doc_ids))
        assert example_id.startswith(f"{DocumentSource.PYLON.value}:")

        for doc_id in all_slim_doc_ids:
            assert ":issue:" in doc_id, f"Expected issue ID, got: {doc_id}"
