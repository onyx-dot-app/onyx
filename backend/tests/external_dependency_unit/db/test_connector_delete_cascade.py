from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.connector import delete_connector
from onyx.db.connector_credential_pair import remove_credential_from_connector
from onyx.db.enums import IndexingStatus
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import IndexAttempt
from onyx.db.models import IndexAttemptError
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.indexing_helpers import make_cc_pair


def _add_index_attempt_with_error(
    db_session: Session,
    cc_pair_id: int,
) -> tuple[int, int]:
    index_attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair_id,
        search_settings_id=None,
        from_beginning=False,
        status=IndexingStatus.COMPLETED_WITH_ERRORS,
    )
    db_session.add(index_attempt)
    db_session.flush()

    index_attempt_error = IndexAttemptError(
        index_attempt_id=index_attempt.id,
        connector_credential_pair_id=cc_pair_id,
        failure_message="test failure",
    )
    db_session.add(index_attempt_error)
    db_session.commit()

    return index_attempt.id, index_attempt_error.id


def _cleanup_connector_rows(
    db_session: Session,
    connector_id: int,
    credential_id: int,
    cc_pair_id: int,
) -> None:
    db_session.rollback()
    db_session.query(IndexAttemptError).filter(
        IndexAttemptError.connector_credential_pair_id == cc_pair_id
    ).delete(synchronize_session="fetch")
    db_session.query(IndexAttempt).filter(
        IndexAttempt.connector_credential_pair_id == cc_pair_id
    ).delete(synchronize_session="fetch")
    db_session.query(ConnectorCredentialPair).filter(
        ConnectorCredentialPair.id == cc_pair_id
    ).delete(synchronize_session="fetch")
    db_session.query(Connector).filter(Connector.id == connector_id).delete(
        synchronize_session="fetch"
    )
    db_session.query(Credential).filter(Credential.id == credential_id).delete(
        synchronize_session="fetch"
    )
    db_session.commit()


def _assert_index_attempt_rows_deleted(
    db_session: Session,
    cc_pair_id: int,
    index_attempt_id: int,
    index_attempt_error_id: int,
) -> None:
    db_session.expire_all()
    assert (
        db_session.query(IndexAttempt)
        .filter(
            IndexAttempt.id == index_attempt_id,
            IndexAttempt.connector_credential_pair_id == cc_pair_id,
        )
        .one_or_none()
        is None
    )
    assert (
        db_session.query(IndexAttemptError)
        .filter(
            IndexAttemptError.id == index_attempt_error_id,
            IndexAttemptError.connector_credential_pair_id == cc_pair_id,
        )
        .one_or_none()
        is None
    )
    assert (
        db_session.query(IndexAttempt)
        .filter(IndexAttempt.connector_credential_pair_id == cc_pair_id)
        .count()
        == 0
    )
    assert (
        db_session.query(IndexAttemptError)
        .filter(IndexAttemptError.connector_credential_pair_id == cc_pair_id)
        .count()
        == 0
    )


def test_remove_credential_from_connector_deletes_index_attempt_rows(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    admin_user = create_test_user(db_session, "cc_pair_delete", role=UserRole.ADMIN)
    cc_pair = make_cc_pair(db_session)
    connector_id = cc_pair.connector_id
    credential_id = cc_pair.credential_id
    cc_pair_id = cc_pair.id
    index_attempt_id, index_attempt_error_id = _add_index_attempt_with_error(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
    )

    try:
        response = remove_credential_from_connector(
            connector_id=connector_id,
            credential_id=credential_id,
            user=admin_user,
            db_session=db_session,
        )

        assert response.success is True
        assert (
            db_session.query(ConnectorCredentialPair)
            .filter(ConnectorCredentialPair.id == cc_pair_id)
            .one_or_none()
            is None
        )
        _assert_index_attempt_rows_deleted(
            db_session=db_session,
            cc_pair_id=cc_pair_id,
            index_attempt_id=index_attempt_id,
            index_attempt_error_id=index_attempt_error_id,
        )
    finally:
        _cleanup_connector_rows(
            db_session=db_session,
            connector_id=connector_id,
            credential_id=credential_id,
            cc_pair_id=cc_pair_id,
        )


def test_delete_connector_deletes_index_attempt_rows(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    cc_pair = make_cc_pair(db_session)
    connector_id = cc_pair.connector_id
    credential_id = cc_pair.credential_id
    cc_pair_id = cc_pair.id
    index_attempt_id, index_attempt_error_id = _add_index_attempt_with_error(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
    )

    try:
        response = delete_connector(
            db_session=db_session,
            connector_id=connector_id,
        )
        db_session.commit()

        assert response.success is True
        assert (
            db_session.query(Connector)
            .filter(Connector.id == connector_id)
            .one_or_none()
            is None
        )
        assert (
            db_session.query(ConnectorCredentialPair)
            .filter(ConnectorCredentialPair.id == cc_pair_id)
            .one_or_none()
            is None
        )
        _assert_index_attempt_rows_deleted(
            db_session=db_session,
            cc_pair_id=cc_pair_id,
            index_attempt_id=index_attempt_id,
            index_attempt_error_id=index_attempt_error_id,
        )
    finally:
        _cleanup_connector_rows(
            db_session=db_session,
            connector_id=connector_id,
            credential_id=credential_id,
            cc_pair_id=cc_pair_id,
        )
