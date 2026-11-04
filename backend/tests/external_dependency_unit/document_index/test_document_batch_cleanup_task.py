"""Guards the batched prune / connector-deletion cleanup task against real
Postgres, Redis and OpenSearch: one batch deletes the docs only this cc_pair
holds, re-syncs the docs another cc_pair still holds, skips ids already gone,
records and clears port orphan candidates, and on the last retry hands every
remaining doc to reconciliation and counts each as a failed prune doc."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from celery.result import EagerResult
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.shared.tasks import (
    document_batch_by_cc_pair_cleanup_task,
)
from onyx.db.document import (
    get_document_connector_counts,
    upsert_document_by_connector_credential_pair,
)
from onyx.db.models import ConnectorCredentialPair, PortOrphanCandidate
from onyx.db.models import Document as DbDocument
from onyx.db.port_orphan_candidate import (
    get_port_orphan_candidate_doc_ids,
    record_port_orphan_candidates,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.interfaces import TenantState
from onyx.document_index.opensearch.client import OpenSearchIndexClient
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.document_index.opensearch.schema import get_opensearch_doc_chunk_id
from onyx.redis.redis_connector import RedisConnector
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.document_index.conftest import (
    make_chunk,
    make_indexing_metadata,
)
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    get_doc_row,
    make_cc_pair,
)

TENANT_ID = POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
CHUNKS_PER_DOC = 2
TASKS_MODULE = "onyx.background.celery.tasks.shared.tasks"


class _Batch(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    pair: ConnectorCredentialPair
    other: ConnectorCredentialPair
    exclusive_ids: list[str]
    shared_id: str
    missing_id: str

    @property
    def all_ids(self) -> list[str]:
        return [*self.exclusive_ids, self.shared_id, self.missing_id]


def _add_indexed_document(
    db_session: Session,
    index: OpenSearchDocumentIndex,
    pairs: list[ConnectorCredentialPair],
    doc_id: str,
) -> None:
    db_session.add(DbDocument(id=doc_id, semantic_id=doc_id, chunk_count=2))
    db_session.commit()
    for pair in pairs:
        upsert_document_by_connector_credential_pair(
            db_session, pair.connector_id, pair.credential_id, [doc_id]
        )
    index.index(
        chunks=[make_chunk(doc_id, chunk_id=i) for i in range(CHUNKS_PER_DOC)],
        indexing_metadata=make_indexing_metadata([doc_id], [0], [CHUNKS_PER_DOC]),
    )


@pytest.fixture
def batch(
    db_session: Session,
    opensearch_index: OpenSearchDocumentIndex,
    test_index_name: str,
) -> Generator[_Batch, None, None]:
    pair = make_cc_pair(db_session)
    other = make_cc_pair(db_session)
    prefix = f"batch-cleanup-{uuid4().hex[:8]}"
    seeded = _Batch(
        pair=pair,
        other=other,
        exclusive_ids=[f"{prefix}-a", f"{prefix}-b"],
        shared_id=f"{prefix}-shared",
        missing_id=f"{prefix}-missing",
    )
    for doc_id in seeded.exclusive_ids:
        _add_indexed_document(db_session, opensearch_index, [pair], doc_id)
    _add_indexed_document(db_session, opensearch_index, [pair, other], seeded.shared_id)
    # Delete-by-query only sees refreshed chunks.
    client = OpenSearchIndexClient(index_name=test_index_name)
    client.refresh_index()
    try:
        yield seeded
    finally:
        db_session.rollback()
        client.refresh_index()
        opensearch_index.delete_documents(seeded.all_ids)
        RedisConnector(TENANT_ID, pair.id).prune.reset()
        db_session.query(PortOrphanCandidate).filter(
            PortOrphanCandidate.cc_pair_id.in_([pair.id, other.id])
        ).delete(synchronize_session=False)
        db_session.commit()
        for cc_pair in (pair, other):
            cleanup_cc_pair(db_session, cc_pair)
        # The failure path leaves unlinked rows that no cc_pair cleanup owns.
        db_session.query(DbDocument).filter(DbDocument.id.in_(seeded.all_ids)).delete(
            synchronize_session=False
        )
        db_session.commit()


def _connector_counts(db_session: Session, doc_ids: list[str]) -> dict[str, int]:
    db_session.expire_all()
    return dict(get_document_connector_counts(db_session, doc_ids))


def _run_cleanup(batch: _Batch, prune_cc_pair_id: int | None = None) -> EagerResult:
    return document_batch_by_cc_pair_cleanup_task.apply(
        args=(
            batch.all_ids,
            batch.pair.connector_id,
            batch.pair.credential_id,
            TENANT_ID,
        ),
        kwargs={"prune_cc_pair_id": prune_cc_pair_id},
    )


def test_batch_deletes_exclusive_docs_and_resyncs_shared_docs(
    db_session: Session,
    batch: _Batch,
    opensearch_index: OpenSearchDocumentIndex,
    test_index_name: str,
) -> None:
    with patch(
        f"{TASKS_MODULE}.get_default_document_index", return_value=opensearch_index
    ):
        result = _run_cleanup(batch)

    assert result.successful(), result.traceback
    assert result.result is True

    for doc_id in batch.exclusive_ids:
        assert get_doc_row(db_session, doc_id) is None
    assert opensearch_index.get_documents_with_any_chunk(batch.exclusive_ids) == set()

    assert get_doc_row(db_session, batch.shared_id) is not None
    assert _connector_counts(db_session, [batch.shared_id]) == {batch.shared_id: 1}
    # The index carries the shared doc's new links on every chunk.
    client = OpenSearchIndexClient(index_name=test_index_name)
    tenant_state = TenantState(tenant_id=TENANT_ID, multitenant=False)
    for chunk_index in range(CHUNKS_PER_DOC):
        chunk = client.get_document(
            get_opensearch_doc_chunk_id(
                tenant_state=tenant_state,
                document_id=batch.shared_id,
                chunk_index=chunk_index,
            )
        )
        assert chunk.cc_pair_ids == [batch.other.id]


def test_port_candidates_recorded_for_deleted_docs_and_cleared_for_shared(
    db_session: Session,
    batch: _Batch,
    opensearch_index: OpenSearchDocumentIndex,
) -> None:
    search_settings_id = get_current_search_settings(db_session).id
    # A candidate from an earlier delete of the shared doc, which stays live.
    record_port_orphan_candidates(
        db_session, search_settings_id, batch.pair.id, [batch.shared_id]
    )
    db_session.commit()

    with (
        patch(
            f"{TASKS_MODULE}.get_default_document_index",
            return_value=opensearch_index,
        ),
        patch(
            f"{TASKS_MODULE}.port_target_settings_id", return_value=search_settings_id
        ),
        patch(
            "onyx.db.port_orphan_candidate.port_target_settings_id",
            return_value=search_settings_id,
        ),
    ):
        result = _run_cleanup(batch)

    assert result.successful(), result.traceback
    db_session.expire_all()
    assert sorted(
        get_port_orphan_candidate_doc_ids(db_session, search_settings_id, batch.pair.id)
    ) == sorted(batch.exclusive_ids)
    assert (
        get_port_orphan_candidate_doc_ids(
            db_session, search_settings_id, batch.other.id
        )
        == []
    )


def test_last_retry_hands_every_doc_to_reconciliation_and_counts_prune_failures(
    db_session: Session,
    batch: _Batch,
) -> None:
    db_session.expire_all()
    modified_before = {
        doc_id: row.last_modified
        for doc_id in [*batch.exclusive_ids, batch.shared_id]
        if (row := get_doc_row(db_session, doc_id)) is not None
    }
    failing_index = MagicMock()
    failing_index.delete_documents.side_effect = RuntimeError("index unavailable")

    with patch(
        f"{TASKS_MODULE}.get_default_document_index", return_value=failing_index
    ):
        result = _run_cleanup(batch, prune_cc_pair_id=batch.pair.id)

    assert result.successful(), result.traceback
    assert result.result is False
    max_retries = document_batch_by_cc_pair_cleanup_task.max_retries
    assert max_retries is not None
    assert failing_index.delete_documents.call_count == max_retries + 1

    # Every existing doc lost this cc_pair's link and is dirty for reconciliation.
    counts = _connector_counts(db_session, [*batch.exclusive_ids, batch.shared_id])
    assert counts == {batch.shared_id: 1}
    for doc_id, modified_at in modified_before.items():
        row = get_doc_row(db_session, doc_id)
        assert row is not None
        assert row.last_modified is not None
        assert modified_at is None or row.last_modified > modified_at

    # The missing id is not a failed doc.
    assert RedisConnector(TENANT_ID, batch.pair.id).prune.failed_docs == 3
