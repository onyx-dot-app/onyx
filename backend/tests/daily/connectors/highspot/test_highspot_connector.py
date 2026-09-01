import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.highspot.connector import HighspotConnector
from onyx.connectors.models import Document, HierarchyNode
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(
    TestSecret.HIGHSPOT_KEY,
    TestSecret.HIGHSPOT_SECRET,
)


def load_test_data(file_name: str = "test_highspot_data.json") -> dict:
    current_dir = Path(__file__).parent
    with open(current_dir / file_name, "r") as f:
        return json.load(f)


@pytest.fixture
def highspot_connector(
    test_secrets: dict[TestSecret, str],
) -> HighspotConnector:
    connector = HighspotConnector(
        # This shared workspace has 16 spots; scoping to just this one keeps the
        # test fast and deterministic instead of scanning everything live.
        spot_names=["Test content"],
        batch_size=10,
    )
    connector.load_credentials(
        {
            "highspot_key": test_secrets[TestSecret.HIGHSPOT_KEY],
            "highspot_secret": test_secrets[TestSecret.HIGHSPOT_SECRET],
            "highspot_url": os.environ.get(
                "HIGHSPOT_URL", "https://api-su2.highspot.com/v1.0/"
            ),
        }
    )
    return connector


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_highspot_connector_basic(
    mock_get_api_key: MagicMock,  # noqa: ARG001
    highspot_connector: HighspotConnector,
) -> None:
    all_docs: list[Document] = []
    test_data = load_test_data()
    target_test_doc_id = test_data.get("target_doc_id")
    target_test_doc: Document | None = None

    for doc_batch in highspot_connector.poll_source(0, time.time()):
        for doc in doc_batch:
            if isinstance(doc, HierarchyNode):
                continue
            all_docs.append(doc)
            if doc.id == f"HIGHSPOT_{target_test_doc_id}":
                target_test_doc = doc

    assert len(all_docs) > 0

    if target_test_doc_id and target_test_doc is not None:
        assert target_test_doc.semantic_identifier == test_data.get(
            "semantic_identifier"
        )
        assert target_test_doc.source == DocumentSource.HIGHSPOT
        assert target_test_doc.metadata is not None

        assert len(target_test_doc.sections) == 1
        section = target_test_doc.sections[0]
        assert section.link is not None
        # Don't assert exact text: this is live content that can change independent of this test.
        assert section.text is not None
        assert len(section.text) > 0


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_highspot_connector_slim(
    mock_get_api_key: MagicMock,  # noqa: ARG001
    highspot_connector: HighspotConnector,
) -> None:
    all_full_doc_ids = set()
    for doc_batch in highspot_connector.load_from_state():
        all_full_doc_ids.update(
            [doc.id for doc in doc_batch if not isinstance(doc, HierarchyNode)]
        )

    all_slim_doc_ids = set()
    for slim_doc_batch in highspot_connector.retrieve_all_slim_docs_perm_sync():
        all_slim_doc_ids.update(
            [doc.id for doc in slim_doc_batch if not isinstance(doc, HierarchyNode)]
        )

    assert all_full_doc_ids.issubset(all_slim_doc_ids)
    assert len(all_slim_doc_ids) > 0


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_highspot_connector_poll_source(
    mock_get_api_key: MagicMock,  # noqa: ARG001
    highspot_connector: HighspotConnector,
) -> None:
    test_data = load_test_data()
    poll_source_data = test_data.get("poll_source", {})
    target_doc_id = poll_source_data.get("target_doc_id")

    # Highspot bumps `date_updated` on this item independently of content edits
    # (observed jumping from April 2025 to January 2026 with no changes made), so
    # a fixed historical window eventually excludes it. Anchor the window to the
    # item's current value instead.
    target_item = highspot_connector.client.get_item(target_doc_id)
    updated_at = datetime.fromisoformat(
        target_item["date_updated"].replace("Z", "+00:00")
    )
    start_time = (updated_at - timedelta(days=1)).timestamp()
    end_time = (updated_at + timedelta(days=1)).timestamp()

    all_docs: list[Document] = []
    target_doc: Document | None = None

    for doc_batch in highspot_connector.poll_source(start_time, end_time):
        for doc in doc_batch:
            if isinstance(doc, HierarchyNode):
                continue
            all_docs.append(doc)
            if doc.id == f"HIGHSPOT_{target_doc_id}":
                target_doc = doc

    assert len(all_docs) > 0

    assert target_doc is not None
    assert target_doc.semantic_identifier == poll_source_data.get("semantic_identifier")
    assert target_doc.source == DocumentSource.HIGHSPOT
    assert target_doc.metadata is not None

    assert len(target_doc.sections) == 1
    section = target_doc.sections[0]
    # Highspot's link domain is tenant-specific (this sandbox uses
    # sandbox-onyx.highspot.com), so compare against the item's own `url` fetched
    # above instead of a hardcoded domain that would go stale on its own.
    assert section.link == target_item.get(
        "url", f"https://www.highspot.com/items/{target_doc_id}"
    )
    assert section.text is not None
    assert len(section.text) > 0


def test_highspot_connector_validate_credentials(
    highspot_connector: HighspotConnector,
) -> None:
    assert highspot_connector.validate_credentials() is True
