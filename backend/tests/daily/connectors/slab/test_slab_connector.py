import json
import os
import time
from pathlib import Path

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.slab.connector import SlabConnector


def load_test_data(file_name: str = "test_slab_data.json") -> dict[str, str]:
    current_dir = Path(__file__).parent
    with open(current_dir / file_name, "r") as f:
        return json.load(f)


@pytest.fixture
def slab_connector() -> SlabConnector:
    connector = SlabConnector(
        base_url="https://onyx-test.slab.com/",
    )
    connector.load_credentials(
        {
            "slab_bot_token": os.environ["SLAB_BOT_TOKEN"],
        }
    )
    return connector


@pytest.mark.xfail(
    reason=(
        "Need a test account with a slab subscription to run this test."
        "Trial only lasts 14 days."
    )
)
def test_slab_connector_basic(slab_connector: SlabConnector) -> None:
    all_docs: list[Document] = []
    target_test_doc_id = "jcp6cohu"
    target_test_doc: Document | None = None
    for doc_batch in slab_connector.poll_source(0, time.time()):
        for doc in doc_batch:
            all_docs.append(doc)
            if doc.id == target_test_doc_id:
                target_test_doc = doc

    assert len(all_docs) == 6
    assert target_test_doc is not None

    desired_test_data = load_test_data()
    assert (
        target_test_doc.semantic_identifier == desired_test_data["semantic_identifier"]
    )
    assert target_test_doc.source == DocumentSource.SLAB
    assert target_test_doc.metadata == {}
    assert target_test_doc.primary_owners is None
    assert target_test_doc.secondary_owners is None
    assert target_test_doc.title is None
    assert target_test_doc.from_ingestion_api is False
    assert target_test_doc.additional_info is None

    assert len(target_test_doc.sections) == 1
    section = target_test_doc.sections[0]
    # Need to replace the weird apostrophe with a normal one
    assert section.text is not None
    assert section.text.replace("\u2019", "'") == desired_test_data["section_text"]
    assert section.link == desired_test_data["link"]


@pytest.mark.xfail(
    reason=(
        "Need a test account with a slab subscription to run this test."
        "Trial only lasts 14 days."
    )
)
def test_slab_connector_slim(slab_connector: SlabConnector) -> None:
    # Get all doc IDs from the full connector
    all_full_doc_ids = set()
    for doc_batch in slab_connector.load_from_state():
        all_full_doc_ids.update([doc.id for doc in doc_batch])

    # Get all doc IDs from the slim connector
    all_slim_doc_ids = set()
    for slim_doc_batch in slab_connector.retrieve_all_slim_docs_perm_sync():
        all_slim_doc_ids.update([doc.id for doc in slim_doc_batch])

    # The set of full doc IDs should be always be a subset of the slim doc IDs
    assert all_full_doc_ids.issubset(all_slim_doc_ids)
