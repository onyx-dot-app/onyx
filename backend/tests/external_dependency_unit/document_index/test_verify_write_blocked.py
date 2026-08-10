"""External dependency tests for index verification when the OpenSearch index
carries a write block, as OpenSearch applies at the disk flood-stage watermark.

Regression tests for api-server pods crash-looping on startup while the index
was read_only_allow_delete-blocked: the mapping refresh is a metadata write, so
it is rejected while the block is active, and startup used to treat that as
fatal even though the index was fully readable.
"""

from collections.abc import Generator

import pytest

from onyx.db.enums import EmbeddingPrecision
from onyx.document_index.opensearch.client import (
    OpenSearchIndexClient,
    is_cluster_block_error,
)
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.document_index.opensearch.schema import DocumentSchema
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


def test_put_mapping_rejected_under_write_block(
    write_blocked_index: OpenSearchDocumentIndex,  # noqa: ARG001
    test_index_name: str,
) -> None:
    """Proves the premise: a mapping refresh is a metadata write and the block
    rejects it — and the rejection is recognized as a cluster block error."""
    client = OpenSearchIndexClient(index_name=test_index_name)
    mappings = DocumentSchema.get_document_schema(EMBEDDING_DIM, False)

    with pytest.raises(Exception) as exc_info:
        client.put_mapping(mappings)

    assert is_cluster_block_error(exc_info.value)


def test_verify_succeeds_when_index_write_blocked(
    write_blocked_index: OpenSearchDocumentIndex,
) -> None:
    """An existing, readable index that is merely write-blocked must not fail
    startup verification."""
    write_blocked_index.verify_and_create_index_if_necessary(
        embedding_dim=EMBEDDING_DIM,
        embedding_precision=EmbeddingPrecision.FLOAT,
    )
