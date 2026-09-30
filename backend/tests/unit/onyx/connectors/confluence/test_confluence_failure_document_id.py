"""Confluence's DocumentFailure.document_id must equal the Document.id that the
connector would have built for the same page.

Several consumers key off that equality to reconcile failures against successful
documents, or to feed a failed doc_id straight back into a repair path:

- backend/onyx/background/celery/tasks/docprocessing/tasks.py compares
  `document.id not in failed_document_ids`.
- backend/onyx/background/indexing/run_targeted_reindex.py computes
  `{d.id for d in documents} - failed_ids`.
- backend/onyx/background/celery/celery_utils.py:_get_failure_id reads the same
  field back out.
- ConfluenceConnector.reindex (Resolver.reindex) takes stored failure doc_ids and
  calls _extract_page_id_from_url on them to figure out which pages to re-fetch.

Confluence's Document.id is the page URL (built by build_confluence_document_id).
If a failure's document_id is instead a bare numeric page id, all of the above
break: the failure never matches an indexed document, and _extract_page_id_from_url
cannot parse a bare number out of its URL-shaped regexes, so the page can never be
repaired by a targeted reindex.
"""

from typing import Any
from unittest import mock

from onyx.connectors.confluence.connector import (
    ConfluenceConnector,
    _extract_page_id_from_url,
)
from onyx.connectors.confluence.onyx_confluence import OnyxConfluence
from onyx.connectors.models import ConnectorFailure, Document

_PAGE_ID = "555"

_PAGE: dict[str, Any] = {
    "id": _PAGE_ID,
    "title": "Some Page",
    "_links": {"webui": f"/spaces/TEST/pages/{_PAGE_ID}/Some+Page"},
    "version": {"when": "2024-01-01T12:00:00.000+0000"},
    "history": {"createdDate": "2024-01-01T12:00:00.000+0000"},
}


def _make_connector() -> ConfluenceConnector:
    connector = ConfluenceConnector(
        wiki_base="https://example.atlassian.net/wiki", is_cloud=True
    )
    confluence_client = mock.Mock(spec=OnyxConfluence)
    confluence_client.paginated_cql_retrieval.return_value = iter([])
    connector._confluence_client = confluence_client
    return connector


def test_failure_document_id_matches_success_document_id() -> None:
    """The document_id on a conversion failure must equal the Document.id that
    the same page would have gotten on a successful conversion.

    This is the round-trip invariant the bug violated: the old code put the
    bare numeric page id on DocumentFailure while Document.id was the page URL,
    so they never matched.
    """
    success_connector = _make_connector()
    with mock.patch(
        "onyx.connectors.confluence.connector.extract_text_from_confluence_html",
        return_value="page body text",
    ):
        document = success_connector._convert_page_to_document(_PAGE)
    assert isinstance(document, Document)

    failure_connector = _make_connector()
    with mock.patch(
        "onyx.connectors.confluence.connector.extract_text_from_confluence_html",
        side_effect=RuntimeError("boom"),
    ):
        result = failure_connector._convert_page_to_document(_PAGE)
    assert isinstance(result, ConnectorFailure)
    failed_document = result.failed_document
    assert failed_document is not None

    # Do not hardcode the URL: derive it from the success path so this test
    # stays correct if the id scheme changes.
    assert failed_document.document_id == document.id
    # The failure must not degenerate to the bare numeric page id.
    assert failed_document.document_id != _PAGE_ID


def test_failure_document_id_can_be_repaired_by_reindex() -> None:
    """The document_id a failure carries must be parseable by the connector's
    own reindex path, or a targeted reindex can never repair the page.
    """
    connector = _make_connector()
    with mock.patch(
        "onyx.connectors.confluence.connector.extract_text_from_confluence_html",
        side_effect=RuntimeError("boom"),
    ):
        result = connector._convert_page_to_document(_PAGE)
    assert isinstance(result, ConnectorFailure)
    failed_document = result.failed_document
    assert failed_document is not None

    extracted_page_id = _extract_page_id_from_url(failed_document.document_id)
    assert extracted_page_id is not None
    assert extracted_page_id == _PAGE_ID


def test_failure_before_url_is_built_still_carries_the_url() -> None:
    """A page that breaks after _links is readable must still record the URL.

    The URL is built first, so a later failure (here, a missing title) keeps the
    document_id equal to the Document.id the success path would have produced.
    """
    connector = _make_connector()
    page_without_title = {k: v for k, v in _PAGE.items() if k != "title"}

    result = connector._convert_page_to_document(page_without_title)
    assert isinstance(result, ConnectorFailure)
    failed_document = result.failed_document
    assert failed_document is not None
    assert _extract_page_id_from_url(failed_document.document_id) == _PAGE_ID


def test_failure_before_url_can_be_built_falls_back_to_page_id() -> None:
    """When even the URL cannot be built, the id falls back to the page id.

    batched_doc_ids in connector_runner.py drops failures with a falsy
    document_id, so an empty id would make the failure disappear.
    """
    connector = _make_connector()
    page_without_links = {k: v for k, v in _PAGE.items() if k != "_links"}

    result = connector._convert_page_to_document(page_without_links)
    assert isinstance(result, ConnectorFailure)
    failed_document = result.failed_document
    assert failed_document is not None
    assert failed_document.document_id == _PAGE_ID
