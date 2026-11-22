"""External dependency tests for index.store.preload on new indexes.

Self-hosted indexes preload the files a search scores with, so the first
searches after a restart do not wait on random disk reads. A quantized index
preloads its quantized vectors, not the float32 copy.
"""

import uuid
from unittest.mock import patch

import pytest

from onyx.db.enums import VectorQuantization
from onyx.document_index.interfaces import TenantState
from onyx.document_index.opensearch import schema
from onyx.document_index.opensearch.client import (
    OpenSearchIndexClient,
    wait_for_opensearch_with_timeout,
)
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.document_index.conftest import EMBEDDING_DIM


def _create_index_and_read_preload(
    vector_quantization: VectorQuantization,
) -> list[str] | None:
    """Creates an index through the startup path and returns its preload setting."""
    index_name: str = f"test_store_preload_{uuid.uuid4().hex[:8]}"
    document_index: OpenSearchDocumentIndex = OpenSearchDocumentIndex(
        tenant_state=TenantState(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, multitenant=False
        ),
        index_name=index_name,
        embedding_dim=EMBEDDING_DIM,
        vector_quantization=vector_quantization,
    )
    with OpenSearchIndexClient(index_name=index_name) as client:
        try:
            document_index.verify_and_create_index_if_necessary(
                embedding_dim=EMBEDDING_DIM
            )
            settings, _ = client.get_settings(flat_settings=True)
            return settings.get("index.store.preload")
        finally:
            client.delete_index()


@pytest.mark.parametrize(
    ("vector_quantization", "vector_extension"),
    [
        (VectorQuantization.NONE, "vec"),
        (VectorQuantization.SCALAR_7_BIT, "veq"),
        (VectorQuantization.SCALAR_1_BIT, "veq"),
    ],
)
def test_new_self_hosted_index_preloads_search_files(
    tenant_context: None,  # noqa: ARG001
    vector_quantization: VectorQuantization,
    vector_extension: str,
) -> None:
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")

    with patch.object(schema, "USING_AWS_MANAGED_OPENSEARCH", False):
        preload = _create_index_and_read_preload(vector_quantization)

    assert preload == [vector_extension, "vex", "doc", "tim", "tip", "dvd", "cfs"]


def test_aws_managed_index_does_not_preload() -> None:
    with patch.object(schema, "USING_AWS_MANAGED_OPENSEARCH", True):
        settings = schema.DocumentSchema.get_index_settings_based_on_environment()

    assert "store.preload" not in settings["index"]
