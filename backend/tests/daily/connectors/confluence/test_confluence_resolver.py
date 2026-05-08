"""Tests for ConfluenceConnector.reindex against a real Confluence space."""

import os
import re
import time
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.confluence.connector import ConfluenceConnector
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import EntityFailure
from onyx.connectors.models import HierarchyNode
from tests.daily.connectors.utils import load_all_from_connector
from tests.utils.secret_names import TestSecret

# Confluence's full crawl yields some documents whose `_links.webui`
# points at a space-level URL (e.g. /spaces/KEY/overview) rather than a
# /pages/<id>/<title> path. Targeted reindex parses page ids out of doc
# URLs, so those non-page docs are out of scope and the test inputs
# filter them out.
_PAGE_DOC_ID_RE = re.compile(r"/pages/\d+(?:/|$)")

pytestmark = pytest.mark.secrets(TestSecret.CONFLUENCE_ACCESS_TOKEN)


def _make_connector(space: str, access_token: str) -> ConfluenceConnector:
    connector = ConfluenceConnector(
        wiki_base=os.environ["CONFLUENCE_TEST_SPACE_URL"],
        space=space,
        is_cloud=os.environ.get("CONFLUENCE_IS_CLOUD", "true").lower() == "true",
        page_id=os.environ.get("CONFLUENCE_TEST_PAGE_ID", ""),
    )
    connector.set_credentials_provider(
        OnyxStaticCredentialsProvider(
            None,
            DocumentSource.CONFLUENCE,
            {
                "confluence_username": os.environ["CONFLUENCE_USER_NAME"],
                "confluence_access_token": access_token,
            },
        )
    )
    return connector


@pytest.fixture
def confluence_connector(
    test_secrets: dict[TestSecret, str],
) -> ConfluenceConnector:
    space = os.getenv("CONFLUENCE_TEST_SPACE") or "DailyConne"
    return _make_connector(
        space, test_secrets[TestSecret.CONFLUENCE_ACCESS_TOKEN].strip()
    )


def _crawl_doc_ids(connector: ConfluenceConnector) -> list[str]:
    """Run a normal crawl and collect every page doc_id (URL).

    Resets `seen_hierarchy_node_raw_ids` after the crawl. Production
    instantiates a fresh connector per task, so the dedup set starts
    empty for the reindex flow; without this reset the same in-test
    instance would skip every hierarchy node on the subsequent reindex
    call and `assert len(nodes) >= 1` would silently fail.
    """
    connector.set_allow_images(False)
    result = load_all_from_connector(connector, 0, time.time())
    connector.seen_hierarchy_node_raw_ids = set()
    return [doc.id for doc in result.documents]


def _build_failures(doc_ids: list[str]) -> list[ConnectorFailure]:
    return [
        ConnectorFailure(
            failed_document=DocumentFailure(document_id=link, document_link=link),
            failure_message="Synthetic failure for %s" % link,
        )
        for link in doc_ids
    ]


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_reindex_single_page(
    mock_api_key: MagicMock,  # noqa: ARG001
    confluence_connector: ConfluenceConnector,
) -> None:
    page_doc_ids = [
        d for d in _crawl_doc_ids(confluence_connector) if _PAGE_DOC_ID_RE.search(d)
    ]
    assert page_doc_ids, "Test space must contain at least one /pages/ document"
    target = page_doc_ids[0]

    results = list(confluence_connector.reindex(_build_failures([target])))

    docs = [r for r in results if isinstance(r, Document)]
    failures = [r for r in results if isinstance(r, ConnectorFailure)]
    nodes = [r for r in results if isinstance(r, HierarchyNode)]

    assert len(docs) == 1
    assert docs[0].id == target
    assert len(failures) == 0
    # Space hierarchy node should always be yielded.
    assert len(nodes) >= 1


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_reindex_multiple_pages(
    mock_api_key: MagicMock,  # noqa: ARG001
    confluence_connector: ConfluenceConnector,
) -> None:
    page_doc_ids = [
        d for d in _crawl_doc_ids(confluence_connector) if _PAGE_DOC_ID_RE.search(d)
    ]
    if len(page_doc_ids) < 2:
        pytest.skip(
            "Test space has fewer than two /pages/ documents (space-homepage "
            "docs are filtered out and don't count)"
        )

    results = list(confluence_connector.reindex(_build_failures(page_doc_ids)))

    docs = [r for r in results if isinstance(r, Document)]
    failures = [r for r in results if isinstance(r, ConnectorFailure)]

    assert len(failures) == 0
    assert {d.id for d in docs} == set(page_doc_ids)


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_reindex_unknown_page_yields_failure(
    mock_api_key: MagicMock,  # noqa: ARG001
    confluence_connector: ConfluenceConnector,
) -> None:
    bogus = "%s/spaces/DailyConne/pages/999999999/Nope" % os.environ[
        "CONFLUENCE_TEST_SPACE_URL"
    ].rstrip("/")

    results = list(confluence_connector.reindex(_build_failures([bogus])))

    docs = [r for r in results if isinstance(r, Document)]
    failures = [r for r in results if isinstance(r, ConnectorFailure)]

    assert len(docs) == 0
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == bogus


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_reindex_unparseable_url_yields_failure(
    mock_api_key: MagicMock,  # noqa: ARG001
    confluence_connector: ConfluenceConnector,
) -> None:
    weird = "https://example.com/wiki/display/SPACE/Some-Page"

    results = list(confluence_connector.reindex(_build_failures([weird])))

    docs = [r for r in results if isinstance(r, Document)]
    failures = [r for r in results if isinstance(r, ConnectorFailure)]

    assert len(docs) == 0
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == weird


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_reindex_empty_errors(
    mock_api_key: MagicMock,  # noqa: ARG001
    confluence_connector: ConfluenceConnector,
) -> None:
    assert list(confluence_connector.reindex([])) == []


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_reindex_entity_failures_are_skipped(
    mock_api_key: MagicMock,  # noqa: ARG001
    confluence_connector: ConfluenceConnector,
) -> None:
    entity = ConnectorFailure(
        failed_entity=EntityFailure(entity_id="some_stage"),
        failure_message="retrieval failure",
    )

    assert list(confluence_connector.reindex([entity])) == []
