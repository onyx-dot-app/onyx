"""Coverage for resolving a flagged pair's failures: resolving its latest failed
index attempt, alone or through Resolve all shown, takes the pair out of the
repeated error state and clears its alert, the beat check no longer flags it,
and a pair Cloud paused stays paused. Resolving an older failure keeps the flag."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.docprocessing.utils import (
    is_in_repeated_error_state,
)
from onyx.configs.constants import DocumentSource, NotificationType
from onyx.connectors.models import InputType
from onyx.db.connector_alerts import connector_alert_additional_data
from onyx.db.enums import (
    AccessType,
    CCPairRunKind,
    ConnectorCredentialPairStatus,
    IndexingStatus,
    NotificationSeverity,
)
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    IndexAttempt,
    Notification,
    User,
)
from onyx.db.notification import create_notification, get_notifications
from onyx.db.search_settings import get_current_search_settings
from onyx.server.documents.cc_pair import (
    resolve_cc_pair_runs,
    resolve_matching_cc_pair_runs,
)
from onyx.server.documents.models import (
    CCPairRunKey,
    CCPairRunLevel,
    CCPairRunsResolveMatchingRequest,
    CCPairRunsResolveRequest,
)
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def admin(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "repeated_error_admin", is_admin=True)
    yield user
    db_session.rollback()
    db_session.query(Notification).filter(Notification.user_id == user.id).delete(
        synchronize_session="fetch"
    )
    delete_test_user(db_session, user)
    db_session.commit()


@pytest.fixture
def flagged_pair(
    db_session: Session, admin: User
) -> Generator[ConnectorCredentialPair, None, None]:
    """A pair Cloud paused after it failed, with the alert it raised."""
    owner = create_test_user(db_session, "repeated_error_owner")
    connector = Connector(
        name="Repeated Error Connector",
        source=DocumentSource.GOOGLE_DRIVE,
        input_type=InputType.POLL,
        connector_specific_config={},
        refresh_freq=None,
    )
    db_session.add(connector)
    db_session.flush()
    credential = Credential(credential_json={}, user_id=owner.id, admin_public=True)
    db_session.add(credential)
    db_session.flush()
    pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name="Repeated Error Pair",
        status=ConnectorCredentialPairStatus.PAUSED,
        access_type=AccessType.PUBLIC,
        in_repeated_error_state=True,
    )
    db_session.add(pair)
    db_session.commit()
    create_notification(
        user_id=admin.id,
        notif_type=NotificationType.CONNECTOR_REPEATED_ERRORS,
        db_session=db_session,
        title="Connector failed",
        additional_data=connector_alert_additional_data(pair.id),
        severity=NotificationSeverity.ERROR,
    )
    yield pair
    db_session.rollback()
    db_session.query(IndexAttempt).filter(
        IndexAttempt.connector_credential_pair_id == pair.id
    ).delete(synchronize_session="fetch")
    db_session.commit()
    cleanup_cc_pair(db_session, pair)
    delete_test_user(db_session, owner)
    db_session.commit()


def _failed_attempt(
    db_session: Session, cc_pair: ConnectorCredentialPair, minutes: int
) -> IndexAttempt:
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=get_current_search_settings(db_session).id,
        from_beginning=False,
        status=IndexingStatus.FAILED,
        time_started=_T0 + timedelta(minutes=minutes),
        error_msg="boom",
    )
    db_session.add(attempt)
    db_session.flush()
    attempt.time_created = _T0 + timedelta(minutes=minutes)
    db_session.commit()
    return attempt


def _resolve(
    db_session: Session, user: User, cc_pair: ConnectorCredentialPair, run_id: int
) -> None:
    resolve_cc_pair_runs(
        cc_pair_id=cc_pair.id,
        request=CCPairRunsResolveRequest(
            runs=[CCPairRunKey(kind=CCPairRunKind.INDEXING, attempt_id=run_id)]
        ),
        user=user,
        db_session=db_session,
    )


def _alerts(db_session: Session, user: User) -> list[Notification]:
    return get_notifications(
        user, db_session, notif_type=NotificationType.CONNECTOR_REPEATED_ERRORS
    )


def _flagged_by_beat(db_session: Session, cc_pair: ConnectorCredentialPair) -> bool:
    return is_in_repeated_error_state(
        cc_pair=cc_pair,
        search_settings_id=get_current_search_settings(db_session).id,
        db_session=db_session,
    )


def test_resolving_the_latest_failure_clears_the_flag_and_alert(
    db_session: Session, admin: User, flagged_pair: ConnectorCredentialPair
) -> None:
    latest = _failed_attempt(db_session, flagged_pair, 0)
    assert _flagged_by_beat(db_session, flagged_pair)
    assert len(_alerts(db_session, admin)) == 1

    _resolve(db_session, admin, flagged_pair, latest.id)

    db_session.refresh(flagged_pair)
    assert flagged_pair.in_repeated_error_state is False
    assert _alerts(db_session, admin) == []
    assert not _flagged_by_beat(db_session, flagged_pair)
    # Cloud's auto-pause stays for the admin to lift.
    assert flagged_pair.status == ConnectorCredentialPairStatus.PAUSED


def test_resolving_an_older_failure_keeps_the_flag(
    db_session: Session, admin: User, flagged_pair: ConnectorCredentialPair
) -> None:
    older = _failed_attempt(db_session, flagged_pair, 0)
    _failed_attempt(db_session, flagged_pair, 1)

    _resolve(db_session, admin, flagged_pair, older.id)

    db_session.refresh(flagged_pair)
    assert flagged_pair.in_repeated_error_state is True
    assert len(_alerts(db_session, admin)) == 1
    assert _flagged_by_beat(db_session, flagged_pair)


def test_resolve_all_shown_clears_the_flag_and_alert(
    db_session: Session, admin: User, flagged_pair: ConnectorCredentialPair
) -> None:
    _failed_attempt(db_session, flagged_pair, 0)
    _failed_attempt(db_session, flagged_pair, 1)

    resolve_matching_cc_pair_runs(
        cc_pair_id=flagged_pair.id,
        request=CCPairRunsResolveMatchingRequest(level=CCPairRunLevel.FAILURES),
        user=admin,
        db_session=db_session,
    )

    db_session.refresh(flagged_pair)
    assert flagged_pair.in_repeated_error_state is False
    assert _alerts(db_session, admin) == []
    assert flagged_pair.status == ConnectorCredentialPairStatus.PAUSED
