"""External dependency tests for indices created while ef_search was lower.

ef_search is a dynamic index setting, so startup must raise it in place on an
existing index instead of leaving the old value.
"""

import uuid
from typing import Any

import pytest

from onyx.db.enums import VectorQuantization
from onyx.document_index.interfaces import TenantState
from onyx.document_index.opensearch.client import (
    OpenSearchIndexClient,
    wait_for_opensearch_with_timeout,
)
from onyx.document_index.opensearch.constants import EF_SEARCH
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.document_index.opensearch.schema import DocumentSchema
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.document_index.conftest import EMBEDDING_DIM

_EF_SEARCH_SETTING = "index.knn.algo_param.ef_search"


@pytest.mark.parametrize(
    "old_index_settings",
    [
        pytest.param(
            {"knn": True, "knn.algo_param.ef_search": 100}, id="ef_search_100"
        ),
        pytest.param({"knn": True}, id="ef_search_unset"),
    ],
)
def test_startup_applies_current_ef_search(
    tenant_context: None,  # noqa: ARG001
    old_index_settings: dict[str, Any],
) -> None:
    """Startup on an existing index sets ef_search to EF_SEARCH."""
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")

    index_name: str = f"test_ef_search_{uuid.uuid4().hex[:8]}"
    settings: dict[str, Any] = DocumentSchema.get_index_settings_based_on_environment()
    settings["index"] = {
        **{k: v for k, v in settings["index"].items() if not k.startswith("knn")},
        **old_index_settings,
    }
    with OpenSearchIndexClient(index_name=index_name) as client:
        client.create_index(
            mappings=DocumentSchema.get_document_schema(
                vector_dimension=EMBEDDING_DIM, multitenant=False
            ),
            settings=settings,
        )
        try:
            before, _ = client.get_settings(flat_settings=True)
            assert before.get(_EF_SEARCH_SETTING) != str(EF_SEARCH)

            OpenSearchDocumentIndex(
                tenant_state=TenantState(
                    tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
                    multitenant=False,
                ),
                index_name=index_name,
                embedding_dim=EMBEDDING_DIM,
                vector_quantization=VectorQuantization.NONE,
            ).verify_and_create_index_if_necessary(embedding_dim=EMBEDDING_DIM)

            after, _ = client.get_settings(flat_settings=True)
            assert after.get(_EF_SEARCH_SETTING) == str(EF_SEARCH)
        finally:
            client.delete_index()
