"""Every terminal status write stamps the attempt's finish time, and the attempt
snapshot reports it, falling back to the last heartbeat check for attempts
from before the column existed."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus, IndexingStatus
from onyx.db.index_attempt import (
    mark_attempt_canceled,
    mark_attempt_failed,
    mark_attempt_succeeded,
)
from onyx.db.models import Connector, ConnectorCredentialPair, Credential, IndexAttempt
from onyx.db.search_settings import get_current_search_settings
from onyx.server.documents.models import IndexAttemptSnapshot
from tests.external_dependency_unit.conftest import create_test_user


def _attempt(db_session: Session) -> IndexAttempt:
    owner = create_test_user(db_session, "time_finished_owner")
    connector = Connector(
        name="time finished",
        source=DocumentSource.FILE,
        input_type=InputType.LOAD_STATE,
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
        name="time finished",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
    )
    db_session.add(cc_pair)
    db_session.flush()
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=get_current_search_settings(db_session).id,
        from_beginning=False,
        status=IndexingStatus.IN_PROGRESS,
        time_started=datetime.now(timezone.utc),
    )
    db_session.add(attempt)
    db_session.commit()
    return attempt


def test_terminal_statuses_stamp_the_finish_time(db_session: Session) -> None:
    before = datetime.now(timezone.utc)
    succeeded = _attempt(db_session)
    failed = _attempt(db_session)
    canceled = _attempt(db_session)

    mark_attempt_succeeded(succeeded.id, db_session)
    mark_attempt_failed(failed.id, db_session, failure_reason="boom")
    mark_attempt_canceled(canceled.id, db_session, reason="stopped")

    for attempt in (succeeded, failed, canceled):
        db_session.refresh(attempt)
        assert attempt.time_finished is not None
        assert attempt.time_finished >= before


def test_snapshot_falls_back_to_the_last_heartbeat(db_session: Session) -> None:
    attempt = _attempt(db_session)
    heartbeat = datetime.now(timezone.utc) - timedelta(minutes=3)
    attempt.status = IndexingStatus.SUCCESS
    attempt.last_heartbeat_time = heartbeat
    db_session.commit()

    snapshot = IndexAttemptSnapshot.from_index_attempt_db_model(attempt, error_count=0)

    assert snapshot.time_finished == heartbeat.isoformat()
