"""External dependency tests for behavior when the OpenSearch index carries a
write block, as OpenSearch applies at the disk flood-stage watermark.

Regression tests for api-server pods crash-looping on startup while the index
was read_only_allow_delete-blocked: the mapping refresh is a metadata write, so
it is rejected while the block is active. verify_and_create_index_if_necessary
still raises (callers like embedding-model swaps must not silently continue);
the tolerant call sites — startup's setup_document_indices and the multitenant
DocumentIndex init — catch the block error and proceed degraded.
"""

from collections.abc import Generator
from unittest.mock import patch

import pytest

from onyx.db.enums import EmbeddingPrecision
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch import (
    opensearch_document_index as opensearch_document_index_module,
)
from onyx.document_index.opensearch.client import (
    OpenSearchIndexClient,
    OpenSearchIndexWriteBlockedError,
    is_cluster_block_error,
)
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.indexing.models import IndexingSetting
from onyx.setup import setup_document_indices
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.document_index.conftest import EMBEDDING_DIM

_WRITE_BLOCK_SETTING = "index.blocks.read_only_allow_delete"


@pytest.fixture
def write_blocked_index(
    opensearch_index: OpenSearchDocumentIndex,
    test_index_name: str,
) -> Generator[OpenSearchDocumentIndex, None, None]:
    """Applies the flood-stage write block to the test index for the duration
    of the test. Clearing the block is always permitted, so cleanup works even
    while the block is active."""
    client = OpenSearchIndexClient(index_name=test_index_name)
    client.update_settings({_WRITE_BLOCK_SETTING: True})
    try:
        yield opensearch_index
    finally:
        client.update_settings({_WRITE_BLOCK_SETTING: None})


def test_verify_raises_typed_error_under_write_block(
    write_blocked_index: OpenSearchDocumentIndex,
) -> None:
    """verify_and_create_index_if_necessary keeps raising under the block (a
    caller such as an embedding-model swap must not silently continue). The
    existing-index refresh raises the targeted type — never raised for a
    missing index or blocked creation — chained from the block rejection."""
    with pytest.raises(OpenSearchIndexWriteBlockedError) as exc_info:
        write_blocked_index.verify_and_create_index_if_necessary(
            embedding_dim=EMBEDDING_DIM,
            embedding_precision=EmbeddingPrecision.FLOAT,
        )

    cause = exc_info.value.__cause__
    assert isinstance(cause, Exception)
    assert is_cluster_block_error(cause)


def test_setup_document_indices_succeeds_under_write_block(
    write_blocked_index: OpenSearchDocumentIndex,
) -> None:
    """Startup must survive an existing, readable index that is merely
    write-blocked instead of crash-looping."""
    index_setting = IndexingSetting.model_construct(model_dim=EMBEDDING_DIM)

    assert setup_document_indices(
        document_indices=[write_blocked_index],
        index_setting=index_setting,
        num_attempts=1,
    )


def test_mt_init_survives_write_block_and_is_not_cached(
    write_blocked_index: OpenSearchDocumentIndex,  # noqa: ARG001
    test_index_name: str,
) -> None:
    """Multitenant __init__ tolerates the block without caching the index as
    verified, so the mapping refresh is retried once the block clears."""
    verified_names = (
        opensearch_document_index_module._verified_index_names_for_current_process
    )
    mt_tenant_state = TenantState(
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, multitenant=True
    )
    try:
        with patch.object(
            opensearch_document_index_module,
            "VERIFY_CREATE_OPENSEARCH_INDEX_ON_INIT_MT",
            True,
        ):
            OpenSearchDocumentIndex(
                tenant_state=mt_tenant_state,
                index_name=test_index_name,
                embedding_dim=EMBEDDING_DIM,
                embedding_precision=EmbeddingPrecision.FLOAT,
            )
            assert test_index_name not in verified_names

            OpenSearchIndexClient(index_name=test_index_name).update_settings(
                {_WRITE_BLOCK_SETTING: None}
            )
            OpenSearchDocumentIndex(
                tenant_state=mt_tenant_state,
                index_name=test_index_name,
                embedding_dim=EMBEDDING_DIM,
                embedding_precision=EmbeddingPrecision.FLOAT,
            )
            assert test_index_name in verified_names
    finally:
        verified_names.discard(test_index_name)
