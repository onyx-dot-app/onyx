"""External dependency tests for `scripts/orphan_doc_cleanup_script.py`.

An orphan is a document with no connector/credential pair. The script deletes
its chunks from the document index, then deletes the document from Postgres.
During an index swap, the chunks can be in the primary index, the secondary
(future) index, or both, so the script must clean both indices.

These tests assume Postgres and OpenSearch are running.
"""

import time
import uuid
from collections.abc import Callable, Generator
from unittest.mock import MagicMock, patch

import pytest
from scripts import orphan_doc_cleanup_script
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.context.search.models import IndexFilters
from onyx.db.enums import IndexModelStatus, SwitchoverType, VectorQuantization
from onyx.db.models import Document as DBDocument
from onyx.db.models import SearchSettings
from onyx.db.search_settings import ActiveSearchSettings
from onyx.document_index.interfaces import DocumentSectionRequest, TenantState
from onyx.document_index.opensearch.client import (
    OpenSearchIndexClient,
    wait_for_opensearch_with_timeout,
)
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.kg.models import KGStage
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.document_index.conftest import (
    EMBEDDING_DIM,
    make_chunk,
    make_indexing_metadata,
)

TENANT_ID = POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
CHUNKS_PER_DOC = 3


def _search_settings(index_name: str, status: IndexModelStatus) -> SearchSettings:
    """Search settings for an index that the test creates. Not saved, so other
    tests never see a FUTURE search settings row."""
    return SearchSettings(
        model_name="test-orphan-cleanup-model",
        model_dim=EMBEDDING_DIM,
        normalize=True,
        query_prefix="",
        passage_prefix="",
        provider_type=None,
        index_name=index_name,
        multipass_indexing=False,
        reduced_dimension=None,
        vector_quantization=VectorQuantization.NONE,
        switchover_type=SwitchoverType.REINDEX,
        enable_contextual_rag=False,
        status=status,
    )


def _new_index(name: str) -> OpenSearchDocumentIndex:
    document_index = OpenSearchDocumentIndex(
        tenant_state=TenantState(tenant_id=TENANT_ID, multitenant=False),
        index_name=name,
        embedding_dim=EMBEDDING_DIM,
        vector_quantization=VectorQuantization.NONE,
    )
    document_index.verify_and_create_index_if_necessary(embedding_dim=EMBEDDING_DIM)
    return document_index


def _index_doc(document_index: OpenSearchDocumentIndex, doc_id: str) -> None:
    document_index.index(
        chunks=[
            make_chunk(doc_id, chunk_id=chunk_id) for chunk_id in range(CHUNKS_PER_DOC)
        ],
        indexing_metadata=make_indexing_metadata(
            [doc_id], old_counts=[0], new_counts=[CHUNKS_PER_DOC]
        ),
    )


def _chunk_count(document_index: OpenSearchDocumentIndex, doc_id: str) -> int:
    return len(
        document_index.id_based_retrieval(
            chunk_requests=[DocumentSectionRequest(document_id=doc_id)],
            filters=IndexFilters(access_control_list=None, tenant_id=TENANT_ID),
            batch_retrieval=True,
        )
    )


def _wait_for_chunk_count(
    document_index: OpenSearchDocumentIndex, doc_id: str, expected: int
) -> int:
    """OpenSearch makes writes and deletes visible only after a refresh."""
    deadline = time.monotonic() + 10
    count = _chunk_count(document_index, doc_id)
    while count != expected and time.monotonic() < deadline:
        time.sleep(0.25)
        count = _chunk_count(document_index, doc_id)
    return count


@pytest.fixture
def index_names(
    tenant_context: None,  # noqa: ARG001
) -> Generator[tuple[str, str], None, None]:
    """Creates a primary and a secondary index and yields their names."""
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")
    suffix = uuid.uuid4().hex[:8]
    names = [f"test_orphan_primary_{suffix}", f"test_orphan_secondary_{suffix}"]
    for name in names:
        _new_index(name)
    try:
        yield names[0], names[1]
    finally:
        for name in names:
            OpenSearchIndexClient(index_name=name).delete_index()


def _add_orphans(db_session: Session, doc_ids: list[str]) -> None:
    """Adds documents with no connector/credential pair."""
    for doc_id in doc_ids:
        db_session.add(
            DBDocument(
                id=doc_id,
                semantic_id=doc_id,
                kg_stage=KGStage.NOT_STARTED,
                chunk_count=CHUNKS_PER_DOC,
            )
        )
    db_session.commit()


def _remaining_docs(db_session: Session, doc_ids: list[str]) -> list[str]:
    db_session.expire_all()
    return sorted(
        db_session.scalars(
            select(DBDocument.id).where(DBDocument.id.in_(doc_ids))
        ).all()
    )


def _delete_docs(db_session: Session, doc_ids: list[str]) -> None:
    db_session.rollback()
    for document in db_session.scalars(
        select(DBDocument).where(DBDocument.id.in_(doc_ids))
    ).all():
        db_session.delete(document)
    db_session.commit()


def _patched_orphan_query(
    doc_ids: list[str],
) -> tuple[Callable[[Session, int], list[str]], list[int]]:
    """Runs the real orphan query, but keeps only this test's documents so the
    script leaves orphans from other tests alone. Fails instead of hanging if
    the script keeps asking for the same batch."""
    find_orphans = orphan_doc_cleanup_script._get_orphaned_document_ids
    calls: list[int] = []

    def _find_test_orphans(session: Session, limit: int) -> list[str]:
        calls.append(1)
        assert len(calls) <= 5, "the script keeps retrying the same batch"
        return [
            doc_id
            for doc_id in find_orphans(session, max(limit, 10_000))
            if doc_id in doc_ids
        ]

    return _find_test_orphans, calls


def test_cleanup_deletes_orphans_from_both_indices_and_postgres(
    db_session: Session,
    index_names: tuple[str, str],
) -> None:
    primary_name, secondary_name = index_names
    primary, secondary = _new_index(primary_name), _new_index(secondary_name)
    suffix = uuid.uuid4().hex[:8]
    in_both = f"orphan_in_both_{suffix}"
    # During an index swap, a document can exist in the future index only.
    in_secondary_only = f"orphan_in_secondary_only_{suffix}"
    not_indexed = f"orphan_not_indexed_{suffix}"
    doc_ids = [in_both, in_secondary_only, not_indexed]

    _add_orphans(db_session, doc_ids)
    _index_doc(primary, in_both)
    _index_doc(secondary, in_both)
    _index_doc(secondary, in_secondary_only)
    assert _wait_for_chunk_count(primary, in_both, CHUNKS_PER_DOC) == CHUNKS_PER_DOC
    for doc_id in (in_both, in_secondary_only):
        assert (
            _wait_for_chunk_count(secondary, doc_id, CHUNKS_PER_DOC) == CHUNKS_PER_DOC
        )

    active_search_settings = ActiveSearchSettings(
        primary=_search_settings(primary_name, IndexModelStatus.PRESENT),
        secondary=_search_settings(secondary_name, IndexModelStatus.FUTURE),
    )
    find_test_orphans, _ = _patched_orphan_query(doc_ids)
    try:
        with (
            patch.object(
                orphan_doc_cleanup_script,
                "get_active_search_settings",
                return_value=active_search_settings,
            ),
            patch.object(
                orphan_doc_cleanup_script,
                "_get_orphaned_document_ids",
                side_effect=find_test_orphans,
            ),
        ):
            orphan_doc_cleanup_script.main()

        for doc_id in (in_both, in_secondary_only):
            assert _wait_for_chunk_count(primary, doc_id, 0) == 0
            assert _wait_for_chunk_count(secondary, doc_id, 0) == 0
        assert _remaining_docs(db_session, doc_ids) == []
    finally:
        _delete_docs(db_session, doc_ids)


def test_cleanup_stops_when_no_orphan_in_a_batch_can_be_deleted(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """A batch where every index delete fails would come back unchanged from
    the next query. The script must stop and keep the documents in Postgres."""
    suffix = uuid.uuid4().hex[:8]
    doc_ids = [f"orphan_delete_fails_{i}_{suffix}" for i in range(2)]
    _add_orphans(db_session, doc_ids)
    failing_index = MagicMock()
    failing_index.delete.side_effect = RuntimeError("document index unavailable")
    find_test_orphans, calls = _patched_orphan_query(doc_ids)
    try:
        with (
            patch.object(orphan_doc_cleanup_script, "get_active_search_settings"),
            patch.object(
                orphan_doc_cleanup_script,
                "get_default_document_index",
                return_value=failing_index,
            ),
            patch.object(
                orphan_doc_cleanup_script,
                "_get_orphaned_document_ids",
                side_effect=find_test_orphans,
            ),
        ):
            orphan_doc_cleanup_script.main()

        assert len(calls) == 1
        assert failing_index.delete.call_count == len(doc_ids)
        assert _remaining_docs(db_session, doc_ids) == sorted(doc_ids)
    finally:
        _delete_docs(db_session, doc_ids)
