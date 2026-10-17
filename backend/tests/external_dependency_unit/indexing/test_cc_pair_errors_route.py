"""The pair's indexing errors route narrows to one attempt and to errors whose
message or document id contains the search text, and counts what it lists."""

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus, IndexingStatus
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    IndexAttempt,
    IndexAttemptError,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.server.documents.cc_pair import get_cc_pair_indexing_errors
from tests.external_dependency_unit.conftest import create_test_user


def _cc_pair(db_session: Session) -> ConnectorCredentialPair:
    owner = create_test_user(db_session, "errors_owner")
    connector = Connector(
        name="Errors Test Connector",
        source=DocumentSource.GOOGLE_DRIVE,
        input_type=InputType.POLL,
        connector_specific_config={},
        refresh_freq=None,
        prune_freq=None,
    )
    db_session.add(connector)
    db_session.flush()
    credential = Credential(credential_json={}, user_id=owner.id, admin_public=True)
    db_session.add(credential)
    db_session.flush()
    cc_pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name="Errors Test Pair",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
    )
    db_session.add(cc_pair)
    db_session.commit()
    return cc_pair


def _attempt(db_session: Session, cc_pair: ConnectorCredentialPair) -> IndexAttempt:
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=get_current_search_settings(db_session).id,
        from_beginning=False,
        status=IndexingStatus.COMPLETED_WITH_ERRORS,
    )
    db_session.add(attempt)
    db_session.commit()
    return attempt


def _error(
    db_session: Session,
    attempt: IndexAttempt,
    document_id: str,
    message: str,
    is_resolved: bool = False,
) -> IndexAttemptError:
    error = IndexAttemptError(
        index_attempt_id=attempt.id,
        connector_credential_pair_id=attempt.connector_credential_pair_id,
        document_id=document_id,
        failure_message=message,
        is_resolved=is_resolved,
    )
    db_session.add(error)
    db_session.commit()
    return error


def test_errors_narrow_to_one_attempt_and_to_a_search(db_session: Session) -> None:
    admin = create_test_user(db_session, "errors_admin", is_admin=True)
    cc_pair = _cc_pair(db_session)
    first = _attempt(db_session, cc_pair)
    second = _attempt(db_session, cc_pair)
    eof = _error(db_session, first, "report.pdf", "unexpected EOF while parsing")
    denied = _error(db_session, first, "notes.txt", "permission denied")
    _error(db_session, first, "done.txt", "unexpected EOF", is_resolved=True)
    other = _error(db_session, second, "report-v2.pdf", "unexpected EOF again")

    def errors(index_attempt_id: int | None = None, q: str | None = None) -> list[int]:
        page = get_cc_pair_indexing_errors(
            cc_pair_id=cc_pair.id,
            include_resolved=False,
            page_num=0,
            page_size=10,
            index_attempt_id=index_attempt_id,
            q=q,
            user=admin,
            db_session=db_session,
        )
        assert page.total_items == len(page.items)
        return [error.id for error in page.items]

    assert set(errors(index_attempt_id=first.id)) == {eof.id, denied.id}
    assert errors(index_attempt_id=first.id, q="EOF") == [eof.id]
    assert set(errors(q="report")) == {eof.id, other.id}
    assert errors(index_attempt_id=second.id, q="denied") == []
    assert errors(index_attempt_id=first.id, q="eof") == [eof.id]
    assert errors(q="%") == []
    assert errors(q="   ") == errors()
