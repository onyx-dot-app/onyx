"""What the tabular re-chunk scan selects.

The scan is the migration's only way to reach a document, so anything it
leaves out keeps the old chunker's output for good.
"""

from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.background.indexing.run_tabular_rechunk import TABULAR_CHUNK_CEILING
from onyx.db.document import (
    get_oversized_tabular_documents,
    upsert_document_by_connector_credential_pair,
)
from onyx.db.models import Document as DbDocument
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)


def _scan(db_session: Session) -> list[str]:
    return [
        target.document.id
        for target in get_oversized_tabular_documents(
            db_session,
            chunk_count_above=TABULAR_CHUNK_CEILING,
            after_doc_id=None,
            limit=100,
        )
    ]


def test_the_scan_passes_over_a_hidden_spreadsheet(db_session: Session) -> None:
    """A hidden document's head cannot be read back: id_based_retrieval never
    returns one. Selecting it would only report it as a failure on every pass.
    """
    pair = make_cc_pair(db_session)
    doc_id = f"book-{uuid4().hex[:8]}.csv"
    try:
        db_session.add(
            DbDocument(
                id=doc_id,
                semantic_id=doc_id,
                file_id=f"file-{uuid4().hex[:8]}",
                chunk_count=TABULAR_CHUNK_CEILING + 1,
                hidden=False,
                from_ingestion_api=False,
            )
        )
        db_session.flush()
        upsert_document_by_connector_credential_pair(
            db_session, pair.connector_id, pair.credential_id, [doc_id]
        )
        db_session.commit()

        assert doc_id in _scan(db_session)

        db_session.query(DbDocument).filter(DbDocument.id == doc_id).update(
            {"hidden": True}
        )
        db_session.commit()

        assert doc_id not in _scan(db_session)
    finally:
        cleanup_cc_pair(db_session, pair)
