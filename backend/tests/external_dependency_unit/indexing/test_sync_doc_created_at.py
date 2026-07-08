"""Tests for propagating a newly-supplied ``doc_created_at`` to already-indexed
documents via a metadata-only update (no re-embedding).

Most tests exercise the decision + persistence logic of ``sync_doc_created_at``
against a real Postgres with the document index mocked, so we can assert exactly
which metadata updates are issued. ``sync_doc_created_at`` resolves its own index
handles internally (primary + FUTURE secondary during a swap), so we patch the
resolvers to inject the mock/real indices.

``test_backfill_reaches_primary_and_secondary_indices`` instead drives real
OpenSearch indices to prove the value lands in BOTH the primary and the FUTURE
secondary, so a doc's creation time isn't lost when the secondary is promoted.
"""

from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

import onyx.indexing.indexing_pipeline as indexing_pipeline
from onyx.access.models import DocumentAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.db.enums import EmbeddingPrecision
from onyx.db.models import Document as DbDocument
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
from onyx.indexing.indexing_pipeline import sync_doc_created_at
from onyx.kg.models import KGStage
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

_VECTOR_DIM = 8
_CHUNKS_PER_DOC = 2
_TENANT_STATE = TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False)
_ACCESS_PUBLIC = DocumentAccess.build(
    user_emails=[],
    user_groups=[],
    external_user_emails=[],
    external_user_group_ids=[],
    is_public=True,
)


def _make_doc(doc_id: str, created_at: datetime | None) -> Document:
    return Document(
        id=doc_id,
        sections=[TextSection(text="hello world")],
        source=DocumentSource.FILE,
        semantic_identifier=doc_id,
        metadata={},
        doc_created_at=created_at,
    )


def _add_db_doc(
    db_session: Session,
    doc_id: str,
    doc_created_at: datetime | None,
    chunk_count: int | None = 2,
) -> None:
    db_session.add(
        DbDocument(
            id=doc_id,
            semantic_id=doc_id,
            kg_stage=KGStage.NOT_STARTED,
            chunk_count=chunk_count,
            doc_created_at=doc_created_at,
        )
    )
    db_session.commit()


def _patch_resolvers(
    monkeypatch: pytest.MonkeyPatch, indices: list[object]
) -> MagicMock:
    """Point sync_doc_created_at's internal index resolution at ``indices``.

    Returns the ``get_all_document_indices`` mock so callers can assert the FUTURE
    settings were forwarded. A None ``port_backfill_source_id`` keeps
    ``primary_backfill_in_progress`` False without a DB round-trip.
    """
    fake_active = MagicMock()
    fake_active.primary.port_backfill_source_id = None
    monkeypatch.setattr(
        indexing_pipeline, "get_active_search_settings", lambda _s: fake_active
    )
    mock_get_all = MagicMock(return_value=indices)
    monkeypatch.setattr(indexing_pipeline, "get_all_document_indices", mock_get_all)
    return mock_get_all


def test_patches_and_persists_when_value_newly_supplied(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc_id = f"created-at-sync-{uuid4().hex[:8]}"
    _add_db_doc(db_session, doc_id, doc_created_at=None, chunk_count=3)

    created = datetime(2021, 5, 1, tzinfo=timezone.utc)
    mock_index = MagicMock()
    _patch_resolvers(monkeypatch, [mock_index])

    sync_doc_created_at([_make_doc(doc_id, created)])

    mock_index.update.assert_called_once()
    (requests,) = mock_index.update.call_args.args
    assert len(requests) == 1
    req = requests[0]
    assert req.document_ids == [doc_id]
    assert req.created_at == created
    assert req.doc_id_to_chunk_cnt == {doc_id: 3}

    db_session.expire_all()
    row = db_session.query(DbDocument).filter(DbDocument.id == doc_id).one()
    assert row.doc_created_at == created


def test_noop_when_created_at_unchanged(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc_id = f"created-at-sync-{uuid4().hex[:8]}"
    created = datetime(2021, 5, 1, tzinfo=timezone.utc)
    _add_db_doc(db_session, doc_id, doc_created_at=created)

    mock_index = MagicMock()
    _patch_resolvers(monkeypatch, [mock_index])
    sync_doc_created_at([_make_doc(doc_id, created)])

    mock_index.update.assert_not_called()


def test_noop_when_incoming_created_at_is_none(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc_id = f"created-at-sync-{uuid4().hex[:8]}"
    _add_db_doc(db_session, doc_id, doc_created_at=None)

    mock_index = MagicMock()
    _patch_resolvers(monkeypatch, [mock_index])
    sync_doc_created_at([_make_doc(doc_id, None)])

    mock_index.update.assert_not_called()


def test_skips_document_not_yet_in_postgres(
    db_session: Session,  # noqa: ARG001
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No DB row: brand-new docs are handled by the normal index path, not here.
    doc_id = f"created-at-sync-{uuid4().hex[:8]}"
    mock_index = MagicMock()
    _patch_resolvers(monkeypatch, [mock_index])

    sync_doc_created_at([_make_doc(doc_id, datetime(2021, 5, 1, tzinfo=timezone.utc))])

    mock_index.update.assert_not_called()


def test_skips_document_with_unknown_chunk_count(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An unknown chunk count would make the index update a no-op, so we defer
    # rather than persist a created_at the index never received.
    doc_id = f"created-at-sync-{uuid4().hex[:8]}"
    _add_db_doc(db_session, doc_id, doc_created_at=None, chunk_count=None)

    mock_index = MagicMock()
    _patch_resolvers(monkeypatch, [mock_index])
    sync_doc_created_at([_make_doc(doc_id, datetime(2021, 5, 1, tzinfo=timezone.utc))])

    mock_index.update.assert_not_called()
    db_session.expire_all()
    row = db_session.query(DbDocument).filter(DbDocument.id == doc_id).one()
    assert row.doc_created_at is None


# ---------------------------------------------------------------------------
# Real-index test: backfill must reach BOTH the primary and the FUTURE secondary
# ---------------------------------------------------------------------------


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


def _make_chunk(doc_id: str, chunk_index: int) -> DocumentChunk:
    # created_at defaults to None (empty) — the pre-backfill state we assert on.
    return DocumentChunk(
        document_id=doc_id,
        chunk_index=chunk_index,
        title=None,
        title_vector=None,
        content=f"chunk {chunk_index} of {doc_id}",
        content_vector=[0.1] * _VECTOR_DIM,
        source_type=DocumentSource.FILE.value,
        metadata_list=None,
        last_updated=datetime(2020, 1, 1, tzinfo=timezone.utc),
        public=_ACCESS_PUBLIC.is_public,
        access_control_list=generate_opensearch_filtered_access_control_list(
            _ACCESS_PUBLIC
        ),
        hidden=False,
        global_boost=0,
        semantic_identifier=f"semantic-{doc_id}",
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


def _read_created_at(
    client: OpenSearchIndexClient, doc_id: str, chunk_index: int
) -> datetime | None:
    chunk_id = get_opensearch_doc_chunk_id(
        tenant_state=_TENANT_STATE, document_id=doc_id, chunk_index=chunk_index
    )
    return client.get_document(document_chunk_id=chunk_id).created_at


def test_backfill_reaches_primary_and_secondary_indices(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """During a swap the doc lives in the live primary AND the FUTURE secondary,
    both with an empty created_at. A single sync must patch BOTH so the value
    survives the secondary's promotion, and Postgres records it only after both
    indices are patched.
    """
    primary_name = f"test_created_at_primary_{uuid4().hex[:8]}"
    future_name = f"test_created_at_future_{uuid4().hex[:8]}"
    primary_client = _create_os_index(primary_name)
    future_client = _create_os_index(future_name)
    doc_id = f"created-at-both-{uuid4().hex[:8]}"
    try:
        for client in (primary_client, future_client):
            client.bulk_index_documents(
                documents=[_make_chunk(doc_id, c_i) for c_i in range(_CHUNKS_PER_DOC)],
                tenant_state=_TENANT_STATE,
            )
            client.refresh_index()

        # Pre-state: both indices lack created_at.
        assert _read_created_at(primary_client, doc_id, 0) is None
        assert _read_created_at(future_client, doc_id, 0) is None

        _add_db_doc(
            db_session, doc_id, doc_created_at=None, chunk_count=_CHUNKS_PER_DOC
        )

        pair = OpenSearchIndexPair(
            primary=_index(primary_name),
            secondary=_index(future_name),
            secondary_embedding_dim=_VECTOR_DIM,
            secondary_embedding_precision=EmbeddingPrecision.FLOAT,
        )
        mock_get_all = _patch_resolvers(monkeypatch, [pair])

        created = datetime(2022, 3, 4, tzinfo=timezone.utc)
        sync_doc_created_at([_make_doc(doc_id, created)])

        # The sync forwarded the FUTURE settings, so the secondary is in the view.
        fake_active = indexing_pipeline.get_active_search_settings(db_session)
        assert (
            mock_get_all.call_args.kwargs["secondary_search_settings"]
            is fake_active.secondary
        )

        primary_client.refresh_index()
        future_client.refresh_index()

        # created_at now present on every chunk of BOTH indices.
        for client in (primary_client, future_client):
            for c_i in range(_CHUNKS_PER_DOC):
                assert _read_created_at(client, doc_id, c_i) == created

        db_session.expire_all()
        row = db_session.query(DbDocument).filter(DbDocument.id == doc_id).one()
        assert row.doc_created_at == created
    finally:
        db_session.query(DbDocument).filter(DbDocument.id == doc_id).delete(
            synchronize_session="fetch"
        )
        db_session.commit()
        for client in (primary_client, future_client):
            try:
                client.delete_index()
            except Exception:
                pass
            finally:
                client.close()
