"""An event source's pair is created with the input type that drains it.

Three routes create connectors and the admin UI uses two of them, so the
decision belongs in `create_connector` rather than in one route. A pair
created as `poll` for an event source would never read its queue, and would
look healthy doing it.
"""

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.connector import create_connector, update_connector
from onyx.db.models import Connector
from onyx.server.documents.models import ConnectorBase
from tests.utils.event_sources import event_source_registered

EVENT_SOURCE = DocumentSource.MOCK_CONNECTOR
POLLED_SOURCE = DocumentSource.WEB


@pytest.fixture
def registered_event_source() -> Generator[None, None, None]:
    """Take the source over for this module, then hand it back."""
    with event_source_registered(EVENT_SOURCE):
        yield


def _create(db_session: Session, source: DocumentSource, name: str) -> Connector:
    response = create_connector(
        db_session=db_session,
        connector_data=ConnectorBase(
            name=name,
            source=source,
            input_type=InputType.POLL,
            connector_specific_config={},
            refresh_freq=None,
            prune_freq=None,
            indexing_start=None,
        ),
    )
    db_session.commit()
    return db_session.query(Connector).filter_by(id=response.id).one()


def test_a_registered_event_source_gets_the_event_input_type(
    db_session: Session,
    registered_event_source: None,  # noqa: ARG001
) -> None:
    connector = _create(db_session, EVENT_SOURCE, "event-input-type")
    try:
        assert connector.input_type == InputType.EVENT
    finally:
        db_session.rollback()
        db_session.delete(connector)
        db_session.commit()


def test_a_polled_source_keeps_what_the_caller_asked_for(
    db_session: Session,
    registered_event_source: None,  # noqa: ARG001
) -> None:
    connector = _create(db_session, POLLED_SOURCE, "polled-input-type")
    try:
        assert connector.input_type == InputType.POLL
    finally:
        db_session.rollback()
        db_session.delete(connector)
        db_session.commit()


def test_an_update_cannot_turn_an_event_pair_back_into_a_poll_pair(
    db_session: Session,
    registered_event_source: None,  # noqa: ARG001
) -> None:
    """An edit that sends `poll` would leave the pair never draining its
    queue, and looking healthy doing it."""
    connector = _create(db_session, EVENT_SOURCE, "event-input-type-update")
    try:
        update_connector(
            connector_id=connector.id,
            connector_data=ConnectorBase(
                name="event-input-type-update",
                source=EVENT_SOURCE,
                input_type=InputType.POLL,
                connector_specific_config={},
                refresh_freq=None,
                prune_freq=None,
                indexing_start=None,
            ),
            db_session=db_session,
        )
        db_session.commit()

        assert connector.input_type == InputType.EVENT
    finally:
        db_session.rollback()
        db_session.delete(connector)
        db_session.commit()
