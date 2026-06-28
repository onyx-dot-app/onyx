import time
from collections.abc import Generator
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import PUBLIC_DOC_PAT
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import IndexAttemptMetadata
from onyx.connectors.models import InputType
from onyx.connectors.seafile.connector import SEAFILE_API_TOKEN_KEY
from onyx.connectors.seafile.connector import SeafileCheckpoint
from onyx.connectors.seafile.connector import SeafileConnector
from onyx.context.search.models import IndexFilters
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import EmbeddingPrecision
from onyx.db.hierarchy import get_hierarchy_node_by_raw_id
from onyx.db.hierarchy import get_source_hierarchy_node
from onyx.db.hierarchy import upsert_hierarchy_nodes_batch
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import Document as DBDocument
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.document_index.interfaces_new import DocumentIndex
from onyx.document_index.interfaces_new import DocumentSectionRequest
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.client import wait_for_opensearch_with_timeout
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.indexing.adapters.document_indexing_adapter import (
    DocumentIndexingBatchAdapter,
)
from onyx.indexing.chunker import Chunker
from onyx.indexing.embedder import IndexingEmbedder
from onyx.indexing.indexing_pipeline import index_doc_batch_prepare
from onyx.indexing.indexing_pipeline import run_indexing_pipeline
from onyx.indexing.models import ChunkEmbedding
from onyx.indexing.models import DocAwareChunk
from onyx.indexing.models import IndexChunk
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.utils.pydantic_util import shallow_model_dump
from shared_configs.model_server_models import Embedding
from tests.external_dependency_unit.connectors.seafile.conftest import (
    SeafileTestLibrary,
)
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair

EMBEDDING_DIM = 128
TEST_TENANT_ID = "public"
pytestmark = pytest.mark.usefixtures("full_deployment_setup")


class CharTokenizer(BaseTokenizer):
    """1 character == 1 token. Deterministic and enough for fixture-sized docs."""

    def encode(self, string: str) -> list[int]:
        return [ord(c) for c in string]

    def tokenize(self, string: str) -> list[str]:
        return list(string)

    def decode(self, tokens: list[int]) -> str:
        return "".join(chr(token) for token in tokens)


class _EmbeddingModelStub:
    tokenizer = CharTokenizer()


class DeterministicIndexingEmbedder(IndexingEmbedder):
    def __init__(self) -> None:
        self.embedding_model = _EmbeddingModelStub()

    def embed_chunks(
        self,
        chunks: list[DocAwareChunk],
        tenant_id: str | None = None,  # noqa: ARG002
        request_id: str | None = None,  # noqa: ARG002
    ) -> list[IndexChunk]:
        embedded_chunks: list[IndexChunk] = []
        for chunk in chunks:
            embedding = _embedding_for_text(chunk.content)
            embedded_chunks.append(
                IndexChunk.model_construct(
                    **shallow_model_dump(chunk),
                    embeddings=ChunkEmbedding(
                        full_embedding=embedding,
                        mini_chunk_embeddings=[
                            _embedding_for_text(mini_chunk)
                            for mini_chunk in chunk.mini_chunk_texts or []
                        ],
                    ),
                    title_embedding=_embedding_for_text(
                        chunk.source_document.get_title_for_document_index() or ""
                    ),
                )
            )
        return embedded_chunks


def _embedding_for_text(text: str) -> Embedding:
    vector = [0.0] * EMBEDDING_DIM
    if not text:
        return vector
    for index, char in enumerate(text[:EMBEDDING_DIM]):
        vector[index] = (ord(char) % 37) / 37.0
    return vector


def _connector(seafile_test_library: SeafileTestLibrary) -> SeafileConnector:
    connector = SeafileConnector(
        base_url=seafile_test_library.base_url,
        repo_ids=[seafile_test_library.repo_id],
        path_prefixes=["/docs"],
        allowed_extensions=[".txt", ".md"],
        max_file_size_bytes=200,
        batch_size=10,
    )
    connector.load_credentials({SEAFILE_API_TOKEN_KEY: seafile_test_library.api_token})
    return connector


def _flatten_batches(connector: SeafileConnector) -> list[Document]:
    return [item for item in _drain_checkpoint(connector) if isinstance(item, Document)]


def _flatten_items(connector: SeafileConnector) -> list[Document | HierarchyNode]:
    return _drain_checkpoint(connector)


def _drain_checkpoint(
    connector: SeafileConnector,
    checkpoint: SeafileCheckpoint | None = None,
) -> list[Document | HierarchyNode]:
    next_checkpoint = checkpoint or connector.build_dummy_checkpoint()
    items: list[Document | HierarchyNode] = []
    while True:
        generator = connector.load_from_checkpoint(
            start=0,
            end=1,
            checkpoint=next_checkpoint,
        )
        try:
            while True:
                item = next(generator)
                assert isinstance(item, (Document, HierarchyNode))
                items.append(item)
        except StopIteration as stop:
            next_checkpoint = stop.value

        if not next_checkpoint.has_more:
            return items


@pytest.fixture
def seafile_cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    connector = Connector(
        name=f"test-seafile-connector-{uuid4().hex[:8]}",
        source=DocumentSource.SEAFILE,
        input_type=InputType.POLL,
        connector_specific_config={},
        refresh_freq=None,
        prune_freq=None,
        indexing_start=None,
    )
    db_session.add(connector)
    db_session.flush()

    credential = Credential(
        source=DocumentSource.SEAFILE,
        credential_json={SEAFILE_API_TOKEN_KEY: "test-token"},
    )
    db_session.add(credential)
    db_session.flush()

    pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=f"test-seafile-cc-pair-{uuid4().hex[:8]}",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
        auto_sync_options=None,
    )
    db_session.add(pair)
    db_session.commit()
    db_session.refresh(pair)

    try:
        yield pair
    finally:
        cleanup_cc_pair(db_session, pair)


@pytest.fixture
def seafile_document_index(
    tenant_context: None,  # noqa: ARG001
) -> Generator[OpenSearchDocumentIndex, None, None]:
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is required for the full Seafile indexing test.")

    document_index = OpenSearchDocumentIndex(
        tenant_state=TenantState(tenant_id=TEST_TENANT_ID, multitenant=False),
        index_name=f"test_seafile_{uuid4().hex[:8]}",
        embedding_dim=EMBEDDING_DIM,
        embedding_precision=EmbeddingPrecision.FLOAT,
    )
    document_index.verify_and_create_index_if_necessary(
        embedding_dim=EMBEDDING_DIM,
        embedding_precision=EmbeddingPrecision.FLOAT,
    )

    try:
        yield document_index
    finally:
        client = getattr(document_index, "_client")
        client.delete_index()


def _get_db_document_rows(
    db_session: Session,
    doc_ids: set[str],
) -> dict[str, DBDocument]:
    db_session.expire_all()
    rows = db_session.query(DBDocument).filter(DBDocument.id.in_(doc_ids)).all()
    return {row.id: row for row in rows}


def _get_cc_pair_rows(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    doc_ids: set[str],
) -> list[DocumentByConnectorCredentialPair]:
    db_session.expire_all()
    return (
        db_session.query(DocumentByConnectorCredentialPair)
        .filter(
            DocumentByConnectorCredentialPair.connector_id == cc_pair.connector_id,
            DocumentByConnectorCredentialPair.credential_id == cc_pair.credential_id,
            DocumentByConnectorCredentialPair.id.in_(doc_ids),
        )
        .all()
    )


def _retrieve_indexed_chunks(
    document_index: DocumentIndex,
    doc_ids: set[str],
    timeout_s: float = 10.0,
) -> dict[str, str]:
    filters = IndexFilters(
        access_control_list=[PUBLIC_DOC_PAT],
        tenant_id=TEST_TENANT_ID,
    )
    deadline = time.monotonic() + timeout_s
    retrieved: dict[str, str] = {}

    while time.monotonic() < deadline:
        retrieved = {}
        for doc_id in doc_ids:
            chunks = document_index.id_based_retrieval(
                chunk_requests=[DocumentSectionRequest(document_id=doc_id)],
                filters=filters,
            )
            if chunks:
                retrieved[doc_id] = "\n".join(chunk.content for chunk in chunks)
        if set(retrieved) == doc_ids:
            return retrieved
        time.sleep(0.25)

    pytest.fail(
        f"Timed out waiting for indexed Seafile chunks. "
        f"Expected {sorted(doc_ids)}, got {sorted(retrieved)}."
    )


def test_live_seafile_docs_persist_through_indexing_prepare(
    db_session: Session,
    seafile_test_library: SeafileTestLibrary,
    seafile_cc_pair: ConnectorCredentialPair,
) -> None:
    docs = _flatten_batches(_connector(seafile_test_library))
    doc_ids = {doc.id for doc in docs if doc.id is not None}
    assert doc_ids == {
        f"seafile:{seafile_test_library.repo_id}:{path}"
        for path in seafile_test_library.seeded_text_files
    }

    attempt_metadata = IndexAttemptMetadata(
        connector_id=seafile_cc_pair.connector_id,
        credential_id=seafile_cc_pair.credential_id,
        attempt_id=None,
        request_id="seafile-indexing-prepare-test",
    )

    context = index_doc_batch_prepare(
        documents=docs,
        index_attempt_metadata=attempt_metadata,
        db_session=db_session,
        ignore_time_skip=True,
    )
    assert context is not None
    db_session.commit()

    db_docs = _get_db_document_rows(db_session, doc_ids)
    assert set(db_docs) == doc_ids

    docs_by_id = {doc.id: doc for doc in docs}
    for doc_id, db_doc in db_docs.items():
        source_doc = docs_by_id[doc_id]
        assert db_doc.semantic_id == source_doc.semantic_identifier
        assert db_doc.link == source_doc.sections[0].link
        assert db_doc.doc_metadata == source_doc.doc_metadata
        assert db_doc.doc_metadata is not None
        assert isinstance(db_doc.doc_metadata["size"], int)
        assert db_doc.file_id is None
        # `index_doc_batch_prepare` persists source metadata and joins. The later
        # docprocessing/Vespa stage is responsible for marking doc_updated_at.
        assert db_doc.doc_updated_at is None

    cc_pair_rows = _get_cc_pair_rows(db_session, seafile_cc_pair, doc_ids)
    assert {row.id for row in cc_pair_rows} == doc_ids
    assert all(not row.has_been_indexed for row in cc_pair_rows)

    index_doc_batch_prepare(
        documents=docs,
        index_attempt_metadata=attempt_metadata,
        db_session=db_session,
        ignore_time_skip=True,
    )
    db_session.commit()

    rerun_cc_pair_rows = _get_cc_pair_rows(db_session, seafile_cc_pair, doc_ids)
    assert len(rerun_cc_pair_rows) == len(doc_ids)
    assert {row.id for row in rerun_cc_pair_rows} == doc_ids

    rerun_db_docs = _get_db_document_rows(db_session, doc_ids)
    assert set(rerun_db_docs) == doc_ids
    for doc_id, db_doc in rerun_db_docs.items():
        assert db_doc.doc_metadata == docs_by_id[doc_id].doc_metadata
        assert db_doc.link == docs_by_id[doc_id].sections[0].link


def test_live_seafile_hierarchy_nodes_persist_parent_chain(
    db_session: Session,
    seafile_test_library: SeafileTestLibrary,
) -> None:
    items = _flatten_items(_connector(seafile_test_library))
    nodes = [item for item in items if isinstance(item, HierarchyNode)]

    upsert_hierarchy_nodes_batch(
        db_session=db_session,
        nodes=nodes,
        source=DocumentSource.SEAFILE,
        commit=True,
        is_connector_public=True,
    )

    source_node = get_source_hierarchy_node(db_session, DocumentSource.SEAFILE)
    assert source_node is not None

    library_raw_id = f"seafile:library:{seafile_test_library.repo_id}"
    docs_raw_id = f"seafile:folder:{seafile_test_library.repo_id}:/docs"
    library_node = get_hierarchy_node_by_raw_id(
        db_session, library_raw_id, DocumentSource.SEAFILE
    )
    docs_node = get_hierarchy_node_by_raw_id(
        db_session, docs_raw_id, DocumentSource.SEAFILE
    )

    assert library_node is not None
    assert docs_node is not None
    assert library_node.parent_id == source_node.id
    assert docs_node.parent_id == library_node.id


def test_live_seafile_docs_complete_indexing_pipeline_writes_document_index(
    db_session: Session,
    seafile_test_library: SeafileTestLibrary,
    seafile_cc_pair: ConnectorCredentialPair,
    seafile_document_index: OpenSearchDocumentIndex,
) -> None:
    docs = _flatten_batches(_connector(seafile_test_library))
    doc_ids = {doc.id for doc in docs if doc.id is not None}
    assert doc_ids == {
        f"seafile:{seafile_test_library.repo_id}:{path}"
        for path in seafile_test_library.seeded_text_files
    }

    attempt_metadata = IndexAttemptMetadata(
        connector_id=seafile_cc_pair.connector_id,
        credential_id=seafile_cc_pair.credential_id,
        attempt_id=None,
        request_id="seafile-full-indexing-test",
    )
    adapter = DocumentIndexingBatchAdapter(
        connector_id=seafile_cc_pair.connector_id,
        credential_id=seafile_cc_pair.credential_id,
        tenant_id=TEST_TENANT_ID,
        index_attempt_metadata=attempt_metadata,
    )

    result = run_indexing_pipeline(
        document_batch=docs,
        request_id="seafile-full-indexing-test",
        embedder=DeterministicIndexingEmbedder(),
        document_indices=[cast(DocumentIndex, seafile_document_index)],
        db_session=db_session,
        tenant_id=TEST_TENANT_ID,
        adapter=adapter,
        chunker=Chunker(
            tokenizer=CharTokenizer(),
            enable_multipass=False,
            enable_large_chunks=False,
            enable_contextual_rag=False,
            chunk_token_limit=512,
        ),
        ignore_time_skip=True,
        from_beginning=True,
    )

    assert result.failures == []
    assert result.total_docs == len(doc_ids)
    assert result.new_docs == len(doc_ids)
    assert result.total_chunks >= len(doc_ids)

    retrieved_by_doc_id = _retrieve_indexed_chunks(
        document_index=seafile_document_index,
        doc_ids=doc_ids,
    )
    for path, expected_content in seafile_test_library.seeded_text_files.items():
        doc_id = f"seafile:{seafile_test_library.repo_id}:{path}"
        assert expected_content.strip() in retrieved_by_doc_id[doc_id]

    db_docs = _get_db_document_rows(db_session, doc_ids)
    assert set(db_docs) == doc_ids
    assert all(
        db_doc.chunk_count is not None and db_doc.chunk_count > 0
        for db_doc in db_docs.values()
    )
    assert all(db_doc.doc_updated_at is not None for db_doc in db_docs.values())

    cc_pair_rows = _get_cc_pair_rows(db_session, seafile_cc_pair, doc_ids)
    assert {row.id for row in cc_pair_rows} == doc_ids
    assert all(row.has_been_indexed for row in cc_pair_rows)
