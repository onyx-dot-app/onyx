"""Pruning treats the slim document list as the authoritative "still exists" set.

`celery_utils.extract_ids_from_runnable_connector` collects the IDs a slim
connector yields, and `connector_pruning_generator_task` deletes every indexed
document whose ID is absent from that set. A connector that swallows a fetch
error and omits the page therefore causes silent data loss, so the slim path
must surface the error instead of returning a complete-looking result.
"""

from typing import Any
from unittest.mock import patch

import pytest

from onyx.connectors.drupal_wiki.connector import DrupalWikiConnector
from onyx.connectors.drupal_wiki.utils import build_drupal_wiki_document_id
from onyx.connectors.models import SlimDocument

BASE_URL = "https://wiki.example.com"


class _Page:
    def __init__(self, page_id: int) -> None:
        self.id = page_id
        self.lastModified = 0


def _connector(pages: list[str]) -> DrupalWikiConnector:
    connector = DrupalWikiConnector(base_url=BASE_URL, pages=pages)
    connector._api_token = "token"
    return connector


def _drain(connector: DrupalWikiConnector) -> list[str]:
    ids: list[str] = []
    for batch in connector.retrieve_all_slim_docs():
        ids.extend(doc.id for doc in batch if isinstance(doc, SlimDocument))
    return ids


def test_failed_page_fetch_aborts_instead_of_yielding_a_partial_set() -> None:
    """Page 2 fails. The run must raise, not return only page 1.

    Returning only page 1 is what makes pruning delete page 2 from the index.
    """
    connector = _connector(["1", "2"])

    def _fetch(_self: Any, page_id: int) -> Any:
        if page_id == 2:
            raise RuntimeError("upstream 503")
        return _Page(page_id)

    with (
        patch.object(DrupalWikiConnector, "_get_page_content", _fetch),
        patch.object(DrupalWikiConnector, "_is_page_in_time_range", return_value=True),
        patch.object(DrupalWikiConnector, "_get_page_attachments", return_value=[]),
    ):
        with pytest.raises(RuntimeError, match="upstream 503"):
            _drain(connector)


def test_healthy_run_yields_every_configured_page() -> None:
    """Regression guard: the abort path must not suppress normal results."""
    connector = _connector(["1", "2"])

    with (
        patch.object(
            DrupalWikiConnector,
            "_get_page_content",
            lambda _self, page_id: _Page(page_id),
        ),
        patch.object(DrupalWikiConnector, "_is_page_in_time_range", return_value=True),
        patch.object(DrupalWikiConnector, "_get_page_attachments", return_value=[]),
    ):
        ids = _drain(connector)

    assert ids == [
        build_drupal_wiki_document_id(BASE_URL, 1),
        build_drupal_wiki_document_id(BASE_URL, 2),
    ]
