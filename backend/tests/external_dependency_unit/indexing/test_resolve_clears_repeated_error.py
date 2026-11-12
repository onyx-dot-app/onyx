"""Coverage for resolving a flagged pair's latest failure: it clears the flag and
alert, keeps a Cloud pause, heals a beat that raced it, and leaves retry backoff."""

from collections.abc import Callable, Generator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.docprocessing.tasks import (
    heal_resolved_repeated_error_states,
)
from onyx.background.celery.tasks.docprocessing.utils import (
    NUM_REPEAT_ERRORS_BEFORE_REPEATED_ERROR_STATE,
    is_in_repeated_error_state,
    should_index,
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
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

MakePair = Callable[
    [ConnectorCredentialPairStatus, int | None, bool], ConnectorCredentialPair
]


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
def make_pair(db_session: Session, admin: User) -> Generator[MakePair, None, None]:
    """Makes a pair with the alert its failure raised, flagged or not yet."""
    made: list[tuple[ConnectorCredentialPair, User]] = []

    def make(
        status: ConnectorCredentialPairStatus,
        refresh_freq: int | None,
        flagged: bool,
    ) -> ConnectorCredentialPair:
        owner = create_test_user(db_session, "repeated_error_owner")
        connector = Connector(
            name="Repeated Error Connector",
            source=DocumentSource.GOOGLE_DRIVE,
            input_type=InputType.POLL,
            connector_specific_config={},
            refresh_freq=refresh_freq,
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
            status=status,
            access_type=AccessType.PUBLIC,
            in_repeated_error_state=flagged,
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
        made.append((pair, owner))
        return pair

    yield make
    db_session.rollback()
    for pair, owner in made:
        db_session.query(IndexAttempt).filter(
            IndexAttempt.connector_credential_pair_id == pair.id
        ).delete(synchronize_session="fetch")
        db_session.commit()
        cleanup_cc_pair(db_session, pair)
        delete_test_user(db_session, owner)
        db_session.commit()


def _cloud_paused(make_pair: MakePair) -> ConnectorCredentialPair:
    return make_pair(ConnectorCredentialPairStatus.PAUSED, None, True)


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
    db_session: Session, admin: User, make_pair: MakePair
) -> None:
    pair = _cloud_paused(make_pair)
    latest = _failed_attempt(db_session, pair, 0)
    assert _flagged_by_beat(db_session, pair)
    assert len(_alerts(db_session, admin)) == 1

    _resolve(db_session, admin, pair, latest.id)

    db_session.refresh(pair)
    assert pair.in_repeated_error_state is False
    assert _alerts(db_session, admin) == []
    assert not _flagged_by_beat(db_session, pair)
    # Cloud's auto-pause stays for the admin to lift.
    assert pair.status == ConnectorCredentialPairStatus.PAUSED


def test_resolving_an_older_failure_keeps_the_flag(
    db_session: Session, admin: User, make_pair: MakePair
) -> None:
    pair = _cloud_paused(make_pair)
    older = _failed_attempt(db_session, pair, 0)
    _failed_attempt(db_session, pair, 1)

    _resolve(db_session, admin, pair, older.id)

    db_session.refresh(pair)
    assert pair.in_repeated_error_state is True
    assert len(_alerts(db_session, admin)) == 1
    assert _flagged_by_beat(db_session, pair)


def test_resolve_all_shown_clears_the_flag_and_alert(
    db_session: Session, admin: User, make_pair: MakePair
) -> None:
    pair = _cloud_paused(make_pair)
    _failed_attempt(db_session, pair, 0)
    _failed_attempt(db_session, pair, 1)

    resolve_matching_cc_pair_runs(
        cc_pair_id=pair.id,
        request=CCPairRunsResolveMatchingRequest(level=CCPairRunLevel.FAILURES),
        user=admin,
        db_session=db_session,
    )

    db_session.refresh(pair)
    assert pair.in_repeated_error_state is False
    assert _alerts(db_session, admin) == []
    assert pair.status == ConnectorCredentialPairStatus.PAUSED


def test_the_beat_heals_a_flag_it_set_while_a_resolve_ran(
    db_session: Session, admin: User, make_pair: MakePair
) -> None:
    # The beat raised the alert, the resolve ran, then the beat set the flag and Cloud paused the pair.
    pair = make_pair(ConnectorCredentialPairStatus.ACTIVE, None, False)
    latest = _failed_attempt(db_session, pair, 0)

    _resolve(db_session, admin, pair, latest.id)

    assert _alerts(db_session, admin) == []
    pair.in_repeated_error_state = True
    pair.status = ConnectorCredentialPairStatus.PAUSED
    db_session.commit()

    heal_resolved_repeated_error_states(
        db_session, POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
    )

    db_session.refresh(pair)
    assert pair.in_repeated_error_state is False
    assert pair.status == ConnectorCredentialPairStatus.PAUSED


def test_retries_keep_backing_off_after_a_resolve(
    db_session: Session, admin: User, make_pair: MakePair
) -> None:
    pair = make_pair(ConnectorCredentialPairStatus.INITIAL_INDEXING, 3600, True)
    attempts = [
        _failed_attempt(db_session, pair, minutes)
        for minutes in range(NUM_REPEAT_ERRORS_BEFORE_REPEATED_ERROR_STATE)
    ]
    settings = get_current_search_settings(db_session)

    _resolve(db_session, admin, pair, attempts[-1].id)

    db_session.refresh(pair)
    assert pair.in_repeated_error_state is False
    assert not _flagged_by_beat(db_session, pair)
    # The failed streak still makes a first index wait for its refresh frequency.
    assert not should_index(pair, settings, False, db_session)
