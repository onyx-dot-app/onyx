"""End-to-end deferred-metadata-sync (permission) test for the reindex port.

The existing sync-priority tests mock the document index and assert the producer's
LOW/MEDIUM/HIGH *decision*. This test instead drives the real OpenSearch
`OpenSearchIndexPair.update()` defer path against live indices, proving the
correctness invariant the swap gate relies on:

  D1 (inflight): a metadata/permission update on a doc PRESENT has but FUTURE does
      not yet lands in PRESENT and is *deferred* for FUTURE -- surfaced as the typed
      SecondaryIndexDocumentMissingError carrying exactly the missing doc id.
  flag lifecycle: mark_document_synced_secondary_pending sets the gate flag;
      mark_document_as_synced clears it once FUTURE catches up.
  D4 (no stale-permission leak): after the port copies the doc into FUTURE carrying
      the OLD access, the deferred-sync drain re-applies and FUTURE ends with the
      NEW access -- not the stale one the port wrote.

Uses real Postgres + OpenSearch. Mirrors test_port_flow_e2e's index lifecycle.
"""

from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.access.models import DocumentAccess
from onyx.configs.constants import DocumentSource
from onyx.db.document import count_secondary_only_sync_pending_documents
from onyx.db.document import document_has_indexable_cc_pair
from onyx.db.document import mark_document_as_synced
from onyx.db.document import mark_document_synced_secondary_pending
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import EmbeddingPrecision
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Document as DbDocument
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.document_index.interfaces_new import MetadataUpdateRequest
from onyx.document_index.interfaces_new import SecondaryIndexDocumentMissingError
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.client import OpenSearchIndexClient
from onyx.document_index.opensearch.opensearch_document_index import (
    generate_opensearch_filtered_access_control_list,
)
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.document_index.opensearch.opensearch_document_index import OpenSearchIndexPair
from onyx.document_index.opensearch.schema import DocumentChunk
from onyx.document_index.opensearch.schema import DocumentSchema
from onyx.document_index.opensearch.schema import get_opensearch_doc_chunk_id
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair
from tests.external_dependency_unit.indexing_helpers import make_cc_pair

_VECTOR_DIM = 8  # tiny: this test never re-embeds, it only updates metadata
_CHUNKS_PER_DOC = 2
_PLACEHOLDER_VECTOR = [0.1] * _VECTOR_DIM

# Two distinct *non-public* access states so PRESENT vs FUTURE acls are
# unambiguously comparable (a public state would collapse to an empty acl).
_ACCESS_OLD = DocumentAccess.build(
    user_emails=["bob@example.com"],
    user_groups=[],
    external_user_emails=[],
    external_user_group_ids=[],
    is_public=False,
)
_ACCESS_NEW = DocumentAccess.build(
    user_emails=["alice@example.com"],
    user_groups=[],
    external_user_emails=[],
    external_user_group_ids=[],
    is_public=False,
)
_ACL_OLD = set(generate_opensearch_filtered_access_control_list(_ACCESS_OLD))
_ACL_NEW = set(generate_opensearch_filtered_access_control_list(_ACCESS_NEW))

_TENANT_STATE = TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False)


def _make_chunk(
    document_id: str,
    chunk_index: int,
    access: DocumentAccess,
    last_updated: datetime | None = None,
) -> DocumentChunk:
    # The port re-copies the SAME stored PRESENT chunk on a batch retry, so its
    # doc_updated_at (the external version) is identical across retries — callers
    # exercising the retry race must pin last_updated rather than take now().
    if last_updated is None:
        last_updated = datetime.now(timezone.utc).replace(microsecond=0)
    return DocumentChunk(
        document_id=document_id,
        chunk_index=chunk_index,
        title=None,
        title_vector=None,
        content=f"chunk {chunk_index} of {document_id}",
        content_vector=list(_PLACEHOLDER_VECTOR),
        source_type=DocumentSource.FILE.value,
        metadata_list=None,
        last_updated=last_updated,
        public=access.is_public,
        access_control_list=generate_opensearch_filtered_access_control_list(access),
        hidden=False,
        global_boost=0,
        semantic_identifier=f"semantic-{document_id}",
        image_file_id=None,
        source_links=None,
        blurb="blurb",
        doc_summary="",
        chunk_context="",
        document_sets=None,
        user_projects=None,
        primary_owners=None,
        secondary_owners=None,
        tenant_id=_TENANT_STATE,
    )


def _create_os_index(index_name: str) -> OpenSearchIndexClient:
    client = OpenSearchIndexClient(index_name=index_name)
    client.create_index(
        mappings=DocumentSchema.get_document_schema(
            vector_dimension=_VECTOR_DIM, multitenant=False
        ),
        settings=DocumentSchema.get_index_settings_based_on_environment(),
    )
    return client


def _index(index_name: str) -> OpenSearchDocumentIndex:
    return OpenSearchDocumentIndex(
        tenant_state=_TENANT_STATE,
        index_name=index_name,
        embedding_dim=_VECTOR_DIM,
        embedding_precision=EmbeddingPrecision.FLOAT,
    )


def _read_acl(client: OpenSearchIndexClient, doc_id: str, chunk_index: int) -> set[str]:
    chunk_id = get_opensearch_doc_chunk_id(
        tenant_state=_TENANT_STATE, document_id=doc_id, chunk_index=chunk_index
    )
    return set(client.get_document(document_chunk_id=chunk_id).access_control_list)


@pytest.fixture
def env(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[
    tuple[
        ConnectorCredentialPair,
        str,
        OpenSearchIndexClient,
        OpenSearchIndexClient,
        str,
        str,
    ],
    None,
    None,
]:
    pair = make_cc_pair(db_session)
    doc_id = f"deferdoc-{uuid4().hex[:8]}"
    db_session.add(DbDocument(id=doc_id, semantic_id=doc_id))
    db_session.commit()

    present_name = f"test_defer_present_{uuid4().hex[:8]}"
    future_name = f"test_defer_future_{uuid4().hex[:8]}"
    present_client = _create_os_index(present_name)
    future_client = _create_os_index(future_name)
    try:
        yield pair, doc_id, present_client, future_client, present_name, future_name
    finally:
        db_session.rollback()
        db_session.query(DbDocument).filter(DbDocument.id == doc_id).delete(
            synchronize_session="fetch"
        )
        db_session.commit()
        cleanup_cc_pair(db_session, pair)
        for client in (present_client, future_client):
            try:
                client.delete_index()
            except Exception:
                pass
            finally:
                client.close()


def test_deferred_metadata_sync_no_stale_permission_leak(
    db_session: Session,
    env: tuple[
        ConnectorCredentialPair,
        str,
        OpenSearchIndexClient,
        OpenSearchIndexClient,
        str,
        str,
    ],
) -> None:
    pair, doc_id, present_client, future_client, present_name, future_name = env

    # --- PRESENT has the doc (old access); FUTURE does not yet (mid-port). ---
    present_client.bulk_index_documents(
        documents=[
            _make_chunk(doc_id, c_i, _ACCESS_OLD) for c_i in range(_CHUNKS_PER_DOC)
        ],
        tenant_state=_TENANT_STATE,
    )
    present_client.refresh_index()

    pair_index = OpenSearchIndexPair(
        primary=_index(present_name),
        secondary=_index(future_name),
        secondary_embedding_dim=_VECTOR_DIM,
        secondary_embedding_precision=EmbeddingPrecision.FLOAT,
    )
    req = MetadataUpdateRequest(
        document_ids=[doc_id],
        doc_id_to_chunk_cnt={doc_id: _CHUNKS_PER_DOC},
        access=_ACCESS_NEW,
    )

    baseline_deferred = count_secondary_only_sync_pending_documents(db_session)

    # --- D1: permission change. PRESENT applies; FUTURE is missing -> typed signal. ---
    with pytest.raises(SecondaryIndexDocumentMissingError) as exc:
        pair_index.update([req])
    assert exc.value.document_ids == [doc_id]

    # mimic the sync task's defer branch (this doc has a portable cc_pair)
    mark_document_synced_secondary_pending(doc_id, db_session)

    present_client.refresh_index()
    assert _read_acl(present_client, doc_id, 0) == _ACL_NEW  # PRESENT got new access
    db_session.expire_all()
    doc = db_session.get(DbDocument, doc_id)
    assert doc is not None and doc.secondary_only_sync_pending is True
    assert (
        count_secondary_only_sync_pending_documents(db_session) == baseline_deferred + 1
    )

    # --- the port copies the doc into FUTURE carrying the OLD (pre-change) access. ---
    future_client.bulk_index_documents(
        documents=[
            _make_chunk(doc_id, c_i, _ACCESS_OLD) for c_i in range(_CHUNKS_PER_DOC)
        ],
        tenant_state=_TENANT_STATE,
        use_create_only=True,
    )
    future_client.refresh_index()
    assert _read_acl(future_client, doc_id, 0) == _ACL_OLD  # FUTURE is stale right now

    # --- D4: the deferred-sync drain re-applies; both indices now carry new access. ---
    pair_index.update([req])  # FUTURE present now -> no raise
    mark_document_as_synced(doc_id, db_session)

    future_client.refresh_index()
    assert _read_acl(future_client, doc_id, 0) == _ACL_NEW  # no stale-permission leak
    assert _read_acl(future_client, doc_id, 1) == _ACL_NEW
    db_session.expire_all()
    doc = db_session.get(DbDocument, doc_id)
    assert doc is not None and doc.secondary_only_sync_pending is False
    assert count_secondary_only_sync_pending_documents(db_session) == baseline_deferred


def test_port_batch_retry_does_not_revert_a_newer_metadata_update(
    env: tuple[
        ConnectorCredentialPair,
        str,
        OpenSearchIndexClient,
        OpenSearchIndexClient,
        str,
        str,
    ],
) -> None:
    """The residual race: a port BATCH RETRY re-writes a chunk the port already
    copied, AFTER a live metadata sync applied a newer access to FUTURE. Because
    the port writes create-only, the retry hits an already-existing chunk and is
    rejected as a benign 409 — so the newer metadata update is NOT reverted.

    This exercises a *partial* metadata update followed by a port create-only
    re-index — the interleaving the reindex port can hit when a metadata sync
    lands between two retry attempts of the same batch.
    """
    _, doc_id, _present_client, future_client, _present_name, future_name = env
    future_index = _index(future_name)
    pinned_ts = datetime(
        2026, 6, 1, tzinfo=timezone.utc
    )  # chunk last_updated (create-only ignores it)

    # 1. Port copies the chunk into FUTURE with OLD access (create-only).
    future_client.bulk_index_documents(
        documents=[_make_chunk(doc_id, 0, _ACCESS_OLD, last_updated=pinned_ts)],
        tenant_state=_TENANT_STATE,
        use_create_only=True,
    )
    future_client.refresh_index()
    assert _read_acl(future_client, doc_id, 0) == _ACL_OLD

    # 2. A live metadata sync applies NEW access (partial update, not versioned).
    future_index.update(
        [
            MetadataUpdateRequest(
                document_ids=[doc_id],
                doc_id_to_chunk_cnt={doc_id: 1},
                access=_ACCESS_NEW,
            )
        ]
    )
    future_client.refresh_index()
    assert _read_acl(future_client, doc_id, 0) == _ACL_NEW

    # 3. Port BATCH RETRY re-writes the SAME chunk (OLD access); the chunk already exists.
    future_client.bulk_index_documents(
        documents=[_make_chunk(doc_id, 0, _ACCESS_OLD, last_updated=pinned_ts)],
        tenant_state=_TENANT_STATE,
        use_create_only=True,
    )
    future_client.refresh_index()

    # 4. The newer metadata update must survive — the stale retry is a benign 409.
    assert _read_acl(future_client, doc_id, 0) == _ACL_NEW


def test_metadata_sync_does_not_defer_non_indexable_only_doc(
    db_session: Session,
    env: tuple[
        ConnectorCredentialPair,
        str,
        OpenSearchIndexClient,
        OpenSearchIndexClient,
        str,
        str,
    ],
) -> None:
    """Writer-side deadlock fix: an INVALID-only doc is genuinely missing from FUTURE
    (real update() raises) but must NOT be deferred — its flag would never clear and
    deadlock the swap. The task marks it synced; the gate count stays unchanged."""
    pair, doc_id, present_client, future_client, present_name, future_name = env
    pair.status = ConnectorCredentialPairStatus.INVALID
    db_session.add(
        DocumentByConnectorCredentialPair(
            id=doc_id,
            connector_id=pair.connector_id,
            credential_id=pair.credential_id,
            has_been_indexed=True,
        )
    )
    db_session.commit()
    try:
        present_client.bulk_index_documents(
            documents=[
                _make_chunk(doc_id, c_i, _ACCESS_OLD) for c_i in range(_CHUNKS_PER_DOC)
            ],
            tenant_state=_TENANT_STATE,
        )
        present_client.refresh_index()

        pair_index = OpenSearchIndexPair(
            primary=_index(present_name),
            secondary=_index(future_name),
            secondary_embedding_dim=_VECTOR_DIM,
            secondary_embedding_precision=EmbeddingPrecision.FLOAT,
        )
        req = MetadataUpdateRequest(
            document_ids=[doc_id],
            doc_id_to_chunk_cnt={doc_id: _CHUNKS_PER_DOC},
            access=_ACCESS_NEW,
        )
        baseline = count_secondary_only_sync_pending_documents(db_session)

        # FUTURE genuinely lacks the doc -> the real update still raises (D1).
        with pytest.raises(SecondaryIndexDocumentMissingError):
            pair_index.update([req])

        # the sync task's branch: no portable owner -> mark synced, do NOT defer
        if document_has_indexable_cc_pair(db_session, doc_id):
            mark_document_synced_secondary_pending(doc_id, db_session)
        else:
            mark_document_as_synced(doc_id, db_session)

        db_session.expire_all()
        doc = db_session.get(DbDocument, doc_id)
        assert doc is not None and doc.secondary_only_sync_pending is False
        assert count_secondary_only_sync_pending_documents(db_session) == baseline
    finally:
        db_session.query(DocumentByConnectorCredentialPair).filter(
            DocumentByConnectorCredentialPair.id == doc_id
        ).delete(synchronize_session="fetch")
        db_session.commit()
