"""Covers reading a single document set.

The listing is scoped to the caller, so before this endpoint a client that
managed one set had to fetch every set and filter. The read must stay scoped:
a caller who cannot see a set must get the not-found error, not its contents.
"""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.models import DocumentSet as DocumentSetDBModel
from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.document_set.api import get_document_set
from tests.external_dependency_unit.conftest import create_test_user


def _document_set(
    db_session: Session, *, is_public: bool, owner: User | None = None
) -> int:
    document_set = DocumentSetDBModel(
        name=f"ds-{uuid4().hex[:12]}",
        is_public=is_public,
        user_id=owner.id if owner else None,
    )
    db_session.add(document_set)
    db_session.commit()
    return document_set.id


def test_an_admin_reads_one_set_by_id(db_session: Session) -> None:
    admin = create_test_user(db_session, "docset-get-admin", is_admin=True)
    document_set_id = _document_set(db_session, is_public=True)

    read = get_document_set(
        document_set_id=document_set_id, user=admin, db_session=db_session
    )

    assert read.id == document_set_id
    # The shape matches the listing, so clients parse one model.
    assert read.is_public is True
    assert read.is_up_to_date is not None


def test_a_missing_set_is_not_found(db_session: Session) -> None:
    admin = create_test_user(db_session, "docset-get-missing", is_admin=True)

    with pytest.raises(OnyxError):
        get_document_set(
            document_set_id=2_000_000_000, user=admin, db_session=db_session
        )


def test_a_private_set_stays_hidden_from_a_basic_user(db_session: Session) -> None:
    basic = create_test_user(db_session, "docset-get-basic")
    document_set_id = _document_set(db_session, is_public=False)

    with pytest.raises(OnyxError):
        get_document_set(
            document_set_id=document_set_id, user=basic, db_session=db_session
        )


def test_a_creators_groupless_set_is_found(db_session: Session) -> None:
    # The readable filter needs a public set or group membership, so this set
    # is reachable only through the editable scope. Reading with one scope
    # would answer not-found for a set its own creator manages.
    creator = create_test_user(db_session, "docset-get-creator")
    document_set_id = _document_set(db_session, is_public=False, owner=creator)

    read = get_document_set(
        document_set_id=document_set_id, user=creator, db_session=db_session
    )

    assert read.id == document_set_id
