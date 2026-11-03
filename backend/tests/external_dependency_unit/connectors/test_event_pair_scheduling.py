"""An event pair has no poll interval, so it runs when its inbox has work:
a due change to claim, or a claim to settle. Without that, a pair created
with `refresh_freq=None` would never drain after its first attempt."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.docprocessing.utils import should_index
from onyx.configs.constants import DocumentSource
from onyx.connectors.event_models import ParsedEvent
from onyx.connectors.models import InputType
from onyx.db.connector_event_inbox import record_events
from onyx.db.enums import (
    AccessType,
    ConnectorCredentialPairStatus,
    ConnectorEventStatus,
    IndexingStatus,
)
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    ConnectorEventInbox,
    Credential,
    IndexAttempt,
    SearchSettings,
)
from onyx.db.search_settings import get_current_search_settings

SOURCE = DocumentSource.MOCK_CONNECTOR


@pytest.fixture
def settings(db_session: Session) -> SearchSettings:
    return get_current_search_settings(db_session)


@pytest.fixture
def event_pair(
    db_session: Session, settings: SearchSettings
) -> Generator[ConnectorCredentialPair, None, None]:
    """An event pair whose first attempt has already succeeded."""
    connector = Connector(
        name="event-scheduling-test",
        source=SOURCE,
        input_type=InputType.EVENT,
        connector_specific_config={},
        refresh_freq=None,
    )
    credential = Credential(credential_json={}, source=SOURCE, admin_public=True)
    db_session.add_all([connector, credential])
    db_session.flush()
    pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=f"event-scheduling-pair-{connector.id}",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
        total_docs_indexed=0,
    )
    db_session.add(pair)
    db_session.flush()
    db_session.add(
        IndexAttempt(
            connector_credential_pair_id=pair.id,
            search_settings_id=settings.id,
            from_beginning=False,
            status=IndexingStatus.SUCCESS,
        )
    )
    db_session.commit()
    try:
        yield pair
    finally:
        db_session.rollback()
        db_session.query(IndexAttempt).filter_by(
            connector_credential_pair_id=pair.id
        ).delete()
        db_session.delete(pair)
        db_session.delete(connector)
        db_session.delete(credential)
        db_session.commit()


def _record(db_session: Session, pair: ConnectorCredentialPair) -> None:
    record_events(
        db_session, pair.id, SOURCE, [ParsedEvent(document_id="doc-1", event_key="k")]
    )
    db_session.commit()


def test_an_idle_event_pair_does_not_run(
    db_session: Session, event_pair: ConnectorCredentialPair, settings: SearchSettings
) -> None:
    assert not should_index(event_pair, settings, False, db_session)


def test_a_due_event_runs_the_pair_without_a_refresh_frequency(
    db_session: Session, event_pair: ConnectorCredentialPair, settings: SearchSettings
) -> None:
    _record(db_session, event_pair)

    assert should_index(event_pair, settings, False, db_session)


def test_a_retry_waits_out_its_backoff(
    db_session: Session, event_pair: ConnectorCredentialPair, settings: SearchSettings
) -> None:
    _record(db_session, event_pair)
    db_session.query(ConnectorEventInbox).filter_by(
        connector_credential_pair_id=event_pair.id
    ).update({"available_at": datetime.now(timezone.utc) + timedelta(minutes=5)})
    db_session.commit()

    assert not should_index(event_pair, settings, False, db_session)


def test_an_unsettled_claim_runs_the_pair(
    db_session: Session, event_pair: ConnectorCredentialPair, settings: SearchSettings
) -> None:
    """A claim settles on the next run, and a failed attempt's rows return
    to the queue only then."""
    _record(db_session, event_pair)
    db_session.query(ConnectorEventInbox).filter_by(
        connector_credential_pair_id=event_pair.id
    ).update({"status": ConnectorEventStatus.IN_PROGRESS})
    db_session.commit()

    assert should_index(event_pair, settings, False, db_session)
