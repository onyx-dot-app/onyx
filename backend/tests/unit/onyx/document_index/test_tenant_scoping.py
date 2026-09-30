from unittest.mock import MagicMock, patch

import pytest
from opensearchpy import NotFoundError

from onyx.context.search.models import IndexFilters
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.client import OpenSearchIndexClient
from onyx.document_index.opensearch.schema import TENANT_ID_FIELD_NAME
from onyx.document_index.vespa.vespa_document_index import VespaDocumentIndex


@pytest.mark.parametrize("expired", [False, True])
def test_pit_scan_keeps_tenant_filter_on_every_request(expired: bool) -> None:
    with patch("onyx.document_index.opensearch.client.OpenSearch") as transport:
        client = OpenSearchIndexClient(index_name="test-index")
    search = transport.return_value.search
    empty_page = {"hits": {"hits": []}}
    search.side_effect = (
        [
            NotFoundError(
                404,
                "search_phase_execution_exception",
                {
                    "error": {
                        "root_cause": [{"type": "search_context_missing_exception"}]
                    }
                },
            ),
            empty_page,
        ]
        if expired
        else [empty_page]
    )
    transport.return_value.create_pit.return_value = {"pit_id": "replacement"}
    tenant = TenantState(tenant_id="tenant-a", multitenant=True)
    assert (
        list(client.iter_chunks_for_doc_ids(["shared-id"], tenant_state=tenant)) == []
    )
    assert search.call_count == (2 if expired else 1)
    for call in search.call_args_list:
        assert {"term": {TENANT_ID_FIELD_NAME: {"value": "tenant-a"}}} in call.kwargs[
            "body"
        ]["query"]["bool"]["filter"]


@pytest.mark.parametrize("batch_retrieval", [False, True])
@pytest.mark.parametrize("supplied_tenant", [None, "tenant-b"])
def test_vespa_id_retrieval_pins_tenant_without_mutating_filters(
    batch_retrieval: bool, supplied_tenant: str | None
) -> None:
    index = VespaDocumentIndex(
        index_name="test-index",
        tenant_state=TenantState(tenant_id="tenant-a", multitenant=True),
        large_chunks_enabled=False,
    )
    filters = IndexFilters(
        access_control_list=["user:reader"], tenant_id=supplied_tenant
    )
    with (
        patch(
            "onyx.document_index.vespa.vespa_document_index.batch_search_api_retrieval",
            return_value=[],
        ) as batch,
        patch(
            "onyx.document_index.vespa.vespa_document_index.parallel_visit_api_retrieval",
            return_value=[],
        ) as visit,
    ):
        assert (
            index.id_based_retrieval([], filters, batch_retrieval=batch_retrieval) == []
        )
    retrieval: MagicMock = batch if batch_retrieval else visit
    effective_filters = retrieval.call_args.kwargs["filters"]
    assert effective_filters.tenant_id == "tenant-a"
    assert effective_filters.access_control_list == ["user:reader"]
    assert filters.tenant_id == supplied_tenant
