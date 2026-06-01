"""Regression test for slim-doc / main-doc admission drift on Confluence
attachments.

When image extraction is disabled (`allow_images=False`), the main indexing
pass skips image attachments and never produces a `Document` for them. The
slim-doc pass must apply the same filter; otherwise it emits a `SlimDocument`
for an image the main pass dropped, leaving a permanent `chunk_count IS NULL`
ghost row that the periodic metadata-sync task can never reconcile.
"""

from typing import Any
from unittest import mock

import pytest

from onyx.connectors.confluence.connector import ConfluenceConnector
from onyx.connectors.confluence.onyx_confluence import OnyxConfluence
from onyx.connectors.models import SlimDocument

_PAGE_CQL = "PAGE_CQL"
_ATTACHMENT_CQL = "ATTACHMENT_CQL"

_PAGE = {
    "id": "111",
    "_links": {"webui": "/spaces/X/pages/111/Page"},
    "restrictions": {},
    "space": {"key": "X"},
    "ancestors": [],
}
_IMAGE_ATTACHMENT = {
    "title": "diagram.png",
    "metadata": {"mediaType": "image/png"},
    "_links": {
        "webui": "/pages/viewpageattachments.action?pageId=111&preview=diagram.png"
    },
    "restrictions": {},
    "space": {"key": "X"},
}
_PDF_ATTACHMENT = {
    "title": "spec.pdf",
    "metadata": {"mediaType": "application/pdf"},
    "_links": {"webui": "/download/attachments/111/spec.pdf"},
    "restrictions": {},
    "space": {"key": "X"},
}


@pytest.fixture
def confluence_connector() -> ConfluenceConnector:
    return ConfluenceConnector(
        wiki_base="https://fake-cloud.atlassian.net/wiki",
        is_cloud=True,
    )


def _collect_slim_doc_ids(connector: ConfluenceConnector) -> list[str]:
    """Drive the pruning slim-doc path (include_permissions=False) with a
    fake client and return every emitted SlimDocument id."""

    def fake_paginate(**kwargs: Any) -> Any:
        cql = kwargs.get("cql")
        if cql == _PAGE_CQL:
            return iter([_PAGE])
        if cql == _ATTACHMENT_CQL:
            return iter([_IMAGE_ATTACHMENT, _PDF_ATTACHMENT])
        return iter([])

    fake_client = mock.Mock(spec=OnyxConfluence)
    fake_client.cql_paginate_all_expansions.side_effect = fake_paginate

    with (
        mock.patch.object(
            ConfluenceConnector,
            "confluence_client",
            new_callable=mock.PropertyMock,
            return_value=fake_client,
        ),
        mock.patch.object(
            connector, "_yield_space_hierarchy_nodes", return_value=iter([])
        ),
        mock.patch.object(
            connector, "_yield_ancestor_hierarchy_nodes", return_value=iter([])
        ),
        mock.patch.object(
            connector, "_maybe_yield_page_hierarchy_node", return_value=None
        ),
        mock.patch.object(connector, "_get_parent_hierarchy_raw_id", return_value=None),
        mock.patch.object(
            connector, "_construct_page_cql_query", return_value=_PAGE_CQL
        ),
        mock.patch.object(
            connector, "_construct_attachment_query", return_value=_ATTACHMENT_CQL
        ),
    ):
        ids: list[str] = []
        for batch in connector.retrieve_all_slim_docs():
            for item in batch:
                if isinstance(item, SlimDocument):
                    ids.append(item.id)
    return ids


def test_slim_docs_skip_images_when_allow_images_false(
    confluence_connector: ConfluenceConnector,
) -> None:
    """allow_images=False mirrors the main pass: no SlimDocument for the
    image attachment, so no ghost row is created."""
    confluence_connector.allow_images = False

    ids = _collect_slim_doc_ids(confluence_connector)

    assert not any("viewpageattachments" in doc_id for doc_id in ids)
    # the supported (non-image) attachment is still emitted
    assert any("spec.pdf" in doc_id for doc_id in ids)


def test_slim_docs_include_images_when_allow_images_true(
    confluence_connector: ConfluenceConnector,
) -> None:
    """allow_images=True keeps image attachments, matching the main pass
    which produces Documents for them."""
    confluence_connector.allow_images = True

    ids = _collect_slim_doc_ids(confluence_connector)

    assert any("viewpageattachments" in doc_id for doc_id in ids)
    assert any("spec.pdf" in doc_id for doc_id in ids)
