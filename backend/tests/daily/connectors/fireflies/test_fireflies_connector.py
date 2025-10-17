import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.fireflies.connector import FirefliesConnector
from onyx.connectors.models import Document


def load_test_data(file_name: str = "test_fireflies_data.json") -> dict[str, Any]:
    current_dir = Path(__file__).parent
    with open(current_dir / file_name, "r") as f:
        return json.load(f)


@pytest.fixture
def fireflies_connector() -> FirefliesConnector:
    connector = FirefliesConnector()
    connector.load_credentials(
        {"fireflies_api_key": os.environ["FIREFLIES_API_KEY"]},
    )
    return connector


@pytest.mark.xfail(
    reason="We don't have the key that is stored in GitHub Secrets and the returned data is different than expected",
)
def test_fireflies_connector_basic(fireflies_connector: FirefliesConnector) -> None:
    test_data = load_test_data()

    connector_return_data: list[Document] = next(
        fireflies_connector.poll_source(0, time.time())
    )
    target_doc: Document = connector_return_data[0]

    assert target_doc is not None, "No documents were retrieved from the connector"
    assert (
        target_doc.primary_owners is not None
    ), "No primary owners were retrieved from the connector"

    assert target_doc.id == test_data["id"]
    assert target_doc.semantic_identifier == test_data["semantic_identifier"]
    assert target_doc.primary_owners[0].email == test_data["primary_owners"]
    assert target_doc.secondary_owners == test_data["secondary_owners"]
    assert str(target_doc.doc_updated_at) == test_data["doc_updated_at"]

    assert (
        target_doc.source == DocumentSource.FIREFLIES
    ), "Document source is not fireflies"
    assert target_doc.metadata == test_data["metadata"]

    # Check that the test data and the connector data contain the same section data
    assert {section.text for section in target_doc.sections} == {
        section["text"] for section in test_data["sections"]
    }
    assert {section.link for section in target_doc.sections} == {
        section["link"] for section in test_data["sections"]
    }
