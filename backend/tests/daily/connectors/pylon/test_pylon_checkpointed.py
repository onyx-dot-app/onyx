import os

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.pylon.connector import PylonConnector
from onyx.connectors.pylon.utils import parse_ymd_date
from tests.daily.connectors.utils import load_all_docs_from_checkpoint_connector


@pytest.fixture
def pylon_connector_for_checkpoint() -> PylonConnector:
    """Daily fixture for Pylon checkpointed indexing.

    Env vars:
    - PYLON_API_KEY: Pylon API key
    """
    api_key = os.environ.get("PYLON_API_KEY")

    if not api_key:
        pytest.skip("PYLON_API_KEY not set in environment")

    connector = PylonConnector(
        pylon_entities=["messages"],
        start_date="2025-10-16",
        lookback_days=0,
        batch_size=10,
    )

    connector.load_credentials({"pylon_api_key": api_key})
    return connector


def test_pylon_checkpointed_load(
    pylon_connector_for_checkpoint: PylonConnector,
) -> None:
    start = parse_ymd_date("2025-10-16")  # fixed date to ensure results
    end = start + 24 * 60 * 60  # 1 day after start

    docs = load_all_docs_from_checkpoint_connector(
        connector=pylon_connector_for_checkpoint,
        start=start,
        end=end,
    )

    assert isinstance(docs, list)
    assert len(docs) > 0
    for doc in docs:
        assert doc.source == DocumentSource.PYLON
        assert doc.metadata is not None

        assert doc.id.startswith(
            f"{DocumentSource.PYLON.value}:issue:"
        ), f"Unexpected document ID format: {doc.id}"

        assert "state" in doc.metadata, "Missing 'state' in metadata"
        assert "created_at" in doc.metadata, "Missing 'created_at' in metadata"
        assert "updated_at" in doc.metadata, "Missing 'updated_at' in metadata"

        assert doc.semantic_identifier, "Missing semantic_identifier"

        assert (
            len(doc.sections) >= 1
        ), f"Expected at least 1 section, got {len(doc.sections)}"
