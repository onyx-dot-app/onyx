from unittest.mock import patch

import pytest
from opensearchpy import NotFoundError

from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.client import OpenSearchIndexClient
from onyx.document_index.opensearch.schema import TENANT_ID_FIELD_NAME


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
