"""Regression tests for the Drupal Wiki `DocumentFailure.document_id` invariant.

`DocumentFailure.document_id` must equal the `Document.id` the connector would have
produced for the same source item. Several consumers key off that equality to match
failures back to documents:

- `backend/onyx/background/celery/tasks/docprocessing/tasks.py` checks
  `document.id not in failed_document_ids`.
- `backend/onyx/background/indexing/run_targeted_reindex.py` computes
  `{d.id for d in documents} - failed_ids`.
- `backend/onyx/background/celery/celery_utils.py:_get_failure_id` reads the id back
  off the failure.

If a connector's success path and failure path build the id differently, a page that
failed once and succeeded on retry (or vice versa) will not be recognized as the same
item by these consumers. The Drupal Wiki connector previously used the raw page id
(`str(page.id)`) on the failure path while the success path used
`build_drupal_wiki_document_id(base_url, page.id)` (a full URL), breaking the
invariant at two call sites: `_process_page` and the `load_from_checkpoint` page loop.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

from onyx.connectors.drupal_wiki.connector import DrupalWikiConnector
from onyx.connectors.drupal_wiki.models import DrupalWikiPage
from onyx.connectors.drupal_wiki.utils import build_drupal_wiki_document_id
from onyx.connectors.models import ConnectorFailure, Document
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector

BASE_URL = "https://wiki.example.com"


def _make_connector(pages: list[str] | None = None) -> DrupalWikiConnector:
    connector = DrupalWikiConnector(base_url=BASE_URL, pages=pages)
    connector._api_token = "token"
    connector.headers = {"Accept": "application/json", "Authorization": "Bearer token"}
    return connector


def _make_page(page_id: int) -> DrupalWikiPage:
    return DrupalWikiPage(
        id=page_id,
        title=f"Page {page_id}",
        homeSpace=1,
        lastModified=1_000,
        type="page",
        body="<p>hello</p>",
    )


@contextmanager
def _raise_during_html_parsing() -> Iterator[None]:
    with patch(
        "onyx.connectors.drupal_wiki.connector.parse_html_page_basic",
        side_effect=RuntimeError("boom"),
    ):
        yield


def test_process_page_failure_id_matches_success_id() -> None:
    """`_process_page` must derive the same id on both its success and failure paths."""
    connector = _make_connector()
    page = _make_page(42)
    expected_id = build_drupal_wiki_document_id(BASE_URL, page.id)

    success_result = connector._process_page(page)
    assert isinstance(success_result, Document)
    assert success_result.id == expected_id

    with _raise_during_html_parsing():
        failure_result = connector._process_page(page)
    assert isinstance(failure_result, ConnectorFailure)
    assert failure_result.failed_document is not None
    assert failure_result.failed_document.document_id == expected_id

    # The invariant this test protects: the two ids must match exactly, not merely
    # both be non-empty. A build that reverts to `str(page.id)` on the failure path
    # would make this assertion fail while `success_result.id` stays a full URL.
    assert success_result.id == failure_result.failed_document.document_id


def test_load_from_checkpoint_failure_id_matches_build_helper() -> None:
    """The `load_from_checkpoint` page loop must yield a failure id built the same
    way as `build_drupal_wiki_document_id`, not the raw page id.
    """
    page_id = 99
    connector = _make_connector(pages=[str(page_id)])
    expected_id = build_drupal_wiki_document_id(BASE_URL, page_id)

    with patch.object(
        connector, "_get_page_content", side_effect=RuntimeError("network exploded")
    ):
        outputs = load_everything_from_checkpoint_connector(
            connector, start=0, end=2_000
        )

    failures = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, ConnectorFailure)
    ]
    assert len(failures) == 1
    failure = failures[0]
    assert failure.failed_document is not None
    assert failure.failed_document.document_id == expected_id
    # Guard against a regression back to the raw page id (no scheme, no base_url).
    assert failure.failed_document.document_id != str(page_id)


def test_load_from_checkpoint_failure_id_matches_sibling_success_shape() -> None:
    """With two pages, one succeeding and one failing, the failure id must have the
    exact same shape (base_url + '/node/' prefix) as the sibling success's `Document.id`,
    differing only in the numeric page id.
    """
    good_id = 1
    bad_id = 2
    connector = _make_connector(pages=[str(good_id), str(bad_id)])

    pages_by_id = {good_id: _make_page(good_id), bad_id: _make_page(bad_id)}

    def _get_page_content(page_id: int) -> DrupalWikiPage:
        return pages_by_id[page_id]

    def _process_page(page: DrupalWikiPage) -> Any:
        if page.id == bad_id:
            raise RuntimeError("simulated processing failure")
        return DrupalWikiConnector._process_page(connector, page)

    with (
        patch.object(connector, "_get_page_content", side_effect=_get_page_content),
        patch.object(connector, "_process_page", side_effect=_process_page),
    ):
        outputs = load_everything_from_checkpoint_connector(
            connector, start=0, end=2_000
        )

    items = [item for output in outputs for item in output.items]
    documents = [item for item in items if isinstance(item, Document)]
    failures = [item for item in items if isinstance(item, ConnectorFailure)]

    assert len(documents) == 1
    assert len(failures) == 1
    assert failures[0].failed_document is not None

    success_id = documents[0].id
    failure_id = failures[0].failed_document.document_id

    expected_prefix = f"{BASE_URL}/node/"
    assert success_id == f"{expected_prefix}{good_id}"
    assert failure_id == f"{expected_prefix}{bad_id}"
