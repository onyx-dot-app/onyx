"""Tests that `include_attachments=False` suppresses attachments in both the
main indexing pass and the slim-doc pass, which must stay in lockstep (see
the admission comment in `_retrieve_all_slim_docs`)."""

from typing import Any
from unittest import mock

from onyx.connectors.confluence.connector import ConfluenceConnector
from onyx.connectors.confluence.onyx_confluence import OnyxConfluence
from onyx.connectors.models import SlimDocument

_PAGE_CQL = "PAGE_CQL"
_ATTACHMENT_CQL = "ATTACHMENT_CQL"

_CREATED = {"createdDate": "2023-01-01T12:00:00.000+0000"}
_PAGE = {
    "id": "111",
    "_links": {"webui": "/spaces/X/pages/111/Page"},
    "restrictions": {},
    "space": {"key": "X"},
    "ancestors": [],
    "history": _CREATED,
}
_PDF_ATTACHMENT = {
    "title": "spec.pdf",
    "metadata": {"mediaType": "application/pdf"},
    "_links": {"webui": "/download/attachments/111/spec.pdf"},
    "restrictions": {},
    "space": {"key": "X"},
    "history": _CREATED,
}


def _build_connector(include_attachments: bool) -> ConfluenceConnector:
    return ConfluenceConnector(
        wiki_base="https://fake-cloud.atlassian.net/wiki",
        is_cloud=True,
        include_attachments=include_attachments,
    )


def _collect_slim_doc_ids(
    connector: ConfluenceConnector, fake_client: mock.Mock
) -> list[str]:
    """Drive the pruning slim-doc path (include_permissions=False) with a
    fake client and return every emitted SlimDocument id."""

    def fake_paginate(**kwargs: Any) -> Any:
        cql = kwargs.get("cql")
        if cql == _PAGE_CQL:
            return iter([_PAGE])
        if cql == _ATTACHMENT_CQL:
            return iter([_PDF_ATTACHMENT])
        return iter([])

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


def test_slim_docs_skip_attachments_when_disabled() -> None:
    connector = _build_connector(include_attachments=False)
    fake_client = mock.Mock(spec=OnyxConfluence)

    ids = _collect_slim_doc_ids(connector, fake_client)

    # the page itself is still emitted, but no attachment slim docs
    assert any("/pages/111" in doc_id for doc_id in ids)
    assert not any("spec.pdf" in doc_id for doc_id in ids)
    # the attachment CQL endpoint is never even queried
    queried_cqls = [
        call.kwargs.get("cql")
        for call in fake_client.cql_paginate_all_expansions.call_args_list
    ]
    assert _ATTACHMENT_CQL not in queried_cqls


def test_slim_docs_include_attachments_by_default() -> None:
    """The constructor default (True) preserves the historical behavior of
    existing Confluence connectors, whose stored configs lack the key."""
    connector = ConfluenceConnector(
        wiki_base="https://fake-cloud.atlassian.net/wiki",
        is_cloud=True,
    )
    connector.allow_images = True
    fake_client = mock.Mock(spec=OnyxConfluence)

    ids = _collect_slim_doc_ids(connector, fake_client)

    assert any("/pages/111" in doc_id for doc_id in ids)
    assert any("spec.pdf" in doc_id for doc_id in ids)


def test_main_pass_skips_attachment_fetch_when_disabled() -> None:
    connector = _build_connector(include_attachments=False)
    fake_client = mock.Mock(spec=OnyxConfluence)

    with mock.patch.object(
        ConfluenceConnector,
        "confluence_client",
        new_callable=mock.PropertyMock,
        return_value=fake_client,
    ):
        docs, failures = connector._fetch_page_attachments(_PAGE)

    assert docs == []
    assert failures == []
    fake_client.paginated_cql_retrieval.assert_not_called()
