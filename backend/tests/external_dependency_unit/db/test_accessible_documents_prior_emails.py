"""A user whose email changed keeps access to documents whose synced ACL
names the earlier email (`get_accessible_documents_by_ids`), as search does,
and can attach them to an agent."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.document_access import get_accessible_documents_by_ids
from onyx.db.enums import AccessType
from onyx.db.models import ConnectorCredentialPair, DocumentByConnectorCredentialPair
from onyx.db.models import Document as DbDocument
from onyx.db.persona import upsert_persona
from onyx.kg.models import KGStage
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)


@pytest.fixture
def synced_pair(db_session: Session) -> Iterator[ConnectorCredentialPair]:
    pair = make_cc_pair(db_session, source=DocumentSource.GOOGLE_DRIVE)
    pair.access_type = AccessType.SYNC
    db_session.commit()
    yield pair
    db_session.rollback()
    cleanup_cc_pair(db_session, pair)


def test_a_renamed_users_synced_document_stays_accessible(
    db_session: Session,
    make_test_user: MakeTestUser,
    synced_pair: ConnectorCredentialPair,
) -> None:
    user = make_test_user("prior_emails")
    old_email = f"old_{uuid4().hex[:8]}@example.com"
    user.prior_emails = [old_email]
    document_id = f"prior_emails_{uuid4().hex[:8]}"
    db_session.add(
        DbDocument(
            id=document_id,
            semantic_id="Synced sheet",
            is_public=False,
            external_user_emails=[old_email],
            kg_stage=KGStage.NOT_STARTED,
        )
    )
    db_session.flush()
    db_session.add(
        DocumentByConnectorCredentialPair(
            id=document_id,
            connector_id=synced_pair.connector_id,
            credential_id=synced_pair.credential_id,
            has_been_indexed=True,
        )
    )
    db_session.commit()

    def accessible(prior_emails: list[str] | None) -> list[str]:
        return [
            document.id
            for document in get_accessible_documents_by_ids(
                db_session,
                [document_id],
                user.email,
                [],
                user_id=user.id,
                prior_emails=prior_emails,
            )
        ]

    assert accessible(None) == []
    assert accessible(user.prior_emails) == [document_id]

    persona = upsert_persona(
        user=user,
        name=f"prior emails {uuid4().hex[:8]}",
        description="",
        starter_messages=None,
        system_prompt=None,
        task_prompt=None,
        datetime_aware=None,
        is_public=False,
        tool_ids=[],
        document_ids=[document_id],
        db_session=db_session,
    )
    assert [document.id for document in persona.attached_documents] == [document_id]
