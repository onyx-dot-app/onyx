"""Verify document-set deletion locks mutations and removes group-share rows."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.document_set import delete_document_set
from onyx.db.enums import PermissionAuthority
from onyx.db.models import DocumentSet, DocumentSet__UserGroup, User, UserGroup
from onyx.server.features.document_set import api

DOCUMENT_SET_ID = 42
TENANT_ID = "test-tenant"


def test_delete_endpoint_locks_document_set() -> None:
    document_set = DocumentSet(id=DOCUMENT_SET_ID, name="locked-document-set")
    user = MagicMock(spec=User)
    db_session = MagicMock(spec=Session)

    with (
        patch.object(api, "get_document_set_by_id", return_value=document_set) as get,
        patch.object(
            api,
            "has_permission",
            return_value=PermissionAuthority.GLOBAL,
        ),
        patch.object(api, "mark_document_set_as_to_be_deleted"),
        patch.object(api.client_app, "send_task"),
        patch.object(api, "DISABLE_VECTOR_DB", False),
    ):
        api.delete_document_set(
            document_set_id=DOCUMENT_SET_ID,
            user=user,
            db_session=db_session,
            tenant_id=TENANT_ID,
        )

    get.assert_called_once_with(db_session, DOCUMENT_SET_ID, for_update=True)


def test_delete_document_set_cascades_user_group_link(
    db_session: Session,
) -> None:
    user_group = UserGroup(name=f"doc-set-delete-{uuid4().hex[:12]}")
    document_set = DocumentSet(name=f"doc-set-delete-{uuid4().hex[:12]}")
    db_session.add_all([user_group, document_set])
    db_session.flush()

    document_set_id = document_set.id
    db_session.add(
        DocumentSet__UserGroup(
            document_set_id=document_set_id,
            user_group_id=user_group.id,
        )
    )
    db_session.commit()

    delete_document_set(document_set, db_session)

    link = db_session.scalar(
        select(DocumentSet__UserGroup).where(
            DocumentSet__UserGroup.document_set_id == document_set_id
        )
    )
    assert link is None

    db_session.delete(user_group)
    db_session.commit()
