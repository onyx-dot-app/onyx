"""Tests for propagating a newly-supplied ``doc_created_at`` to already-indexed
documents via a metadata-only update (no re-embedding).

These exercise the decision + persistence logic of ``sync_doc_created_at``
against a real Postgres, with the document index mocked so we can assert exactly
which metadata updates are issued.
"""

from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.db.models import Document as DbDocument
from onyx.indexing.indexing_pipeline import sync_doc_created_at
from onyx.kg.models import KGStage


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


def test_patches_and_persists_when_value_newly_supplied(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    doc_id = f"created-at-sync-{uuid4().hex[:8]}"
    _add_db_doc(db_session, doc_id, doc_created_at=None, chunk_count=3)

    created = datetime(2021, 5, 1, tzinfo=timezone.utc)
    mock_index = MagicMock()

    sync_doc_created_at([_make_doc(doc_id, created)], [mock_index])

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
) -> None:
    doc_id = f"created-at-sync-{uuid4().hex[:8]}"
    created = datetime(2021, 5, 1, tzinfo=timezone.utc)
    _add_db_doc(db_session, doc_id, doc_created_at=created)

    mock_index = MagicMock()
    sync_doc_created_at([_make_doc(doc_id, created)], [mock_index])

    mock_index.update.assert_not_called()


def test_noop_when_incoming_created_at_is_none(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    doc_id = f"created-at-sync-{uuid4().hex[:8]}"
    _add_db_doc(db_session, doc_id, doc_created_at=None)

    mock_index = MagicMock()
    sync_doc_created_at([_make_doc(doc_id, None)], [mock_index])

    mock_index.update.assert_not_called()


def test_skips_document_not_yet_in_postgres(
    db_session: Session,  # noqa: ARG001
    tenant_context: None,  # noqa: ARG001
) -> None:
    # No DB row: brand-new docs are handled by the normal index path, not here.
    doc_id = f"created-at-sync-{uuid4().hex[:8]}"
    mock_index = MagicMock()

    sync_doc_created_at(
        [_make_doc(doc_id, datetime(2021, 5, 1, tzinfo=timezone.utc))],
        [mock_index],
    )

    mock_index.update.assert_not_called()
