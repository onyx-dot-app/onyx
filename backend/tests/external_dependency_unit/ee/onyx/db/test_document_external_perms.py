"""
Tests for upsert_document_external_perms.

Permission sync can enumerate documents that have not been indexed yet (e.g.
docs visible in the source but not yet picked up by an indexing run). Older
versions pre-created skeleton Document rows (empty semantic_id, no chunk_count)
to "stage" permissions for such docs. Those rows are an invalid state for the
OpenSearch backend and flooded document_index_metadata_sync_task with
ChunkCountNotFoundError. These tests lock in the new behavior: permission sync
must never create Document rows, only update existing ones.
"""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ee.onyx.db.document import upsert_document_external_perms
from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.db.models import Document as DbDocument


def _get_document(db_session: Session, doc_id: str) -> DbDocument | None:
    return db_session.scalars(select(DbDocument).where(DbDocument.id == doc_id)).first()


def test_upsert_external_perms_does_not_create_missing_document(
    db_session: Session,
) -> None:
    doc_id = f"test-ghost-doc-{uuid4().hex}"
    external_access = ExternalAccess(
        external_user_emails={"user1@example.com"},
        external_user_group_ids={"group1"},
        is_public=False,
    )

    upsert_document_external_perms(
        db_session=db_session,
        doc_id=doc_id,
        external_access=external_access,
        source_type=DocumentSource.CONFLUENCE,
    )

    # The critical assertion: no skeleton row was created
    assert _get_document(db_session, doc_id) is None


def test_upsert_external_perms_updates_existing_document(
    db_session: Session,
) -> None:
    doc_id = f"test-existing-doc-{uuid4().hex}"
    document = DbDocument(
        id=doc_id,
        semantic_id="Test Document",
        external_user_emails=["old@example.com"],
        external_user_group_ids=[],
        is_public=True,
    )
    db_session.add(document)
    db_session.commit()

    try:
        external_access = ExternalAccess(
            external_user_emails={"new@example.com"},
            external_user_group_ids={"Group1"},
            is_public=False,
        )

        upsert_document_external_perms(
            db_session=db_session,
            doc_id=doc_id,
            external_access=external_access,
            source_type=DocumentSource.CONFLUENCE,
        )

        updated_doc = _get_document(db_session, doc_id)
        assert updated_doc is not None
        assert updated_doc.external_user_emails == ["new@example.com"]
        assert updated_doc.external_user_group_ids == [
            build_ext_group_name_for_onyx(
                ext_group_name="Group1",
                source=DocumentSource.CONFLUENCE,
            )
        ]
        assert updated_doc.is_public is False
        # Permission changes must bump last_modified so the document gets
        # picked up by the document index metadata sync
        assert updated_doc.last_modified is not None
    finally:
        db_session.delete(document)
        db_session.commit()
