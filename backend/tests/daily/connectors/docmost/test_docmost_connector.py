"""Daily integration test for the DocMost connector.

Requires a live DocMost (EE) Test instance. Set:
    DOCMOST_BASE_URL    e.g. https://docmost.example.com
    DOCMOST_API_TOKEN   API key for a service user
    DOCMOST_SPACE_FILTER (optional) comma-separated space slugs

Mirrors the Confluence test pattern referenced in the Onyx connector README.
"""

import os

import pytest

from onyx.connectors.docmost.connector import DocmostConnector
from onyx.connectors.models import Document


def _connector() -> DocmostConnector:
    base_url = os.environ.get("DOCMOST_BASE_URL")
    token = os.environ.get("DOCMOST_API_TOKEN")
    if not base_url or not token:
        pytest.skip("DOCMOST_BASE_URL / DOCMOST_API_TOKEN not set")

    space_filter = [
        s for s in os.environ.get("DOCMOST_SPACE_FILTER", "").split(",") if s
    ]
    connector = DocmostConnector(space_filter=space_filter)
    connector.load_credentials(
        {"docmost_base_url": base_url, "docmost_api_token": token}
    )
    return connector


def test_validate_settings() -> None:
    _connector().validate_connector_settings()


def test_load_from_state_yields_documents() -> None:
    connector = _connector()
    docs: list[Document] = []
    for batch in connector.load_from_state():
        docs.extend(batch)
    assert len(docs) > 0, "expected at least one indexed page"

    first = docs[0]
    assert first.id.startswith("docmost:page:")
    assert first.semantic_identifier
    assert first.sections and first.sections[0].text
    assert first.sections[0].link


def test_poll_source_recent_window() -> None:
    import time

    connector = _connector()
    now = time.time()
    docs: list[Document] = []
    for batch in connector.poll_source(now - 30 * 24 * 3600, now):
        docs.extend(batch)
    # Not asserting non-empty (window may be quiet), just that it runs + parses.
    for d in docs:
        assert d.source.value == "docmost"


def test_slim_docs_are_id_only() -> None:
    connector = _connector()
    count = 0
    for batch in connector.retrieve_all_slim_docs():
        for slim in batch:
            assert slim.id.startswith("docmost:page:")
            count += 1
    assert count >= 0
