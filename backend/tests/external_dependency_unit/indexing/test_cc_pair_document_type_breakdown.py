"""A cc-pair's indexed documents per source MIME type: count and summed size
per type, plus the documents whose source reported no type."""

from collections.abc import Generator
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db import document as document_db
from onyx.db.document import (
    get_document_type_breakdown_for_cc_pair,
    upsert_documents,
)
from onyx.db.engine.sql_engine import get_sqlalchemy_engine
from onyx.db.models import (
    ConnectorCredentialPair,
    Document,
    DocumentByConnectorCredentialPair,
    User,
)
from onyx.document_index.document_metadata import DocumentMetadata
from onyx.server.documents.cc_pair import get_cc_pair_document_types
from onyx.server.documents.models import DocumentTypeCount
from tests.external_dependency_unit.hierarchy.test_cc_pair_hierarchy_breakdown import (
    _cc_pair,
)
from tests.external_dependency_unit.indexing.test_cc_pair_errors_resolve_route import (
    admin,  # noqa: F401
)

_PDF = "application/pdf"
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_PNG = "image/png"


@pytest.fixture()
def session(db_session: Session) -> Generator[Session, None, None]:
    yield db_session
    db_session.rollback()


def _doc(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    mime_type: str | None,
    size_bytes: int | None,
    *,
    has_been_indexed: bool = True,
) -> None:
    document_id = f"type_breakdown_doc_{uuid4().hex}"
    db_session.add(
        Document(
            id=document_id,
            semantic_id=document_id,
            source_mime_type=mime_type,
            source_size_bytes=size_bytes,
        )
    )
    db_session.flush()
    db_session.add(
        DocumentByConnectorCredentialPair(
            id=document_id,
            connector_id=cc_pair.connector_id,
            credential_id=cc_pair.credential_id,
            has_been_indexed=has_been_indexed,
        )
    )
    db_session.flush()


def test_types_count_and_sum_sizes_per_pair(
    session: Session,
    admin: User,  # noqa: F811
) -> None:
    pair = _cc_pair(session, DocumentSource.GOOGLE_DRIVE, {}, indexed=False)
    other_pair = _cc_pair(session, DocumentSource.GOOGLE_DRIVE, {}, indexed=False)
    _doc(session, pair, _PDF, 100)
    _doc(session, pair, _PDF, 250)
    # A PDF without a size still counts, and sized_count and the sum skip it.
    _doc(session, pair, _PDF, None)
    _doc(session, pair, _DOCX, 4000)
    # No document of this type has a size.
    _doc(session, pair, _PNG, None)
    _doc(session, pair, None, None)
    # Not counted: another pair's document, and one not indexed yet.
    _doc(session, other_pair, _PDF, 999)
    _doc(session, pair, _DOCX, 999, has_been_indexed=False)

    breakdown = get_cc_pair_document_types(
        cc_pair_id=pair.id, user=admin, db_session=session
    )

    assert breakdown.types == [
        DocumentTypeCount(mime_type=_PDF, count=3, sized_count=2, size_bytes=350),
        DocumentTypeCount(mime_type=_DOCX, count=1, sized_count=1, size_bytes=4000),
        DocumentTypeCount(mime_type=_PNG, count=1, sized_count=0, size_bytes=None),
    ]
    assert breakdown.untyped_count == 1
    assert not breakdown.timed_out


def test_timeout_returns_an_empty_breakdown_marked_timed_out(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(document_db, "_DOCUMENT_TYPE_BREAKDOWN_TIMEOUT_MS", 200)
    logger = MagicMock()
    monkeypatch.setattr(document_db, "logger", logger)
    # A lock held by another connection makes the read wait past the timeout.
    with get_sqlalchemy_engine().connect() as blocker:
        blocker.execute(text("SET LOCAL lock_timeout = '5s'"))
        blocker.execute(
            text(
                "LOCK TABLE document_by_connector_credential_pair "
                "IN ACCESS EXCLUSIVE MODE"
            )
        )
        breakdown = get_document_type_breakdown_for_cc_pair(session, -1, -1)
        blocker.rollback()

    assert breakdown.types == []
    assert breakdown.untyped_count == 0
    assert breakdown.timed_out
    logger.warning.assert_called_once()
    # The canceled read leaves the caller's transaction usable.
    assert session.scalar(select(1)) == 1


def test_upsert_writes_the_source_type_and_clears_it_when_unreported(
    db_session: Session,
) -> None:
    pair = _cc_pair(db_session, DocumentSource.GOOGLE_DRIVE, {}, indexed=False)
    document_id = f"type_breakdown_upsert_{uuid4().hex}"

    def upsert(mime_type: str | None, size_bytes: int | None) -> Document:
        upsert_documents(
            db_session,
            [
                DocumentMetadata(
                    connector_id=pair.connector_id,
                    credential_id=pair.credential_id,
                    document_id=document_id,
                    semantic_identifier=document_id,
                    first_link="",
                    source_mime_type=mime_type,
                    source_size_bytes=size_bytes,
                )
            ],
        )
        document = db_session.get(Document, document_id)
        assert document is not None
        db_session.refresh(document)
        return document

    try:
        typed = upsert(_PDF, 2048)
        assert (typed.source_mime_type, typed.source_size_bytes) == (_PDF, 2048)
        untyped = upsert(None, None)
        assert (untyped.source_mime_type, untyped.source_size_bytes) == (None, None)
    finally:
        db_session.rollback()
        db_session.execute(delete(Document).where(Document.id == document_id))
        db_session.commit()
