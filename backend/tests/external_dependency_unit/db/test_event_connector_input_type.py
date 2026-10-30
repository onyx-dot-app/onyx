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
from onyx.connectors.event_inbox.source_registry import (
    _SPECS,
    WebhookRequest,
    WebhookSourceSpec,
    register_webhook_source,
)
from onyx.connectors.event_models import EventParseResult
from onyx.connectors.models import InputType
from onyx.db.connector import create_connector
from onyx.db.models import Connector
from onyx.server.documents.models import ConnectorBase

EVENT_SOURCE = DocumentSource.MOCK_CONNECTOR
POLLED_SOURCE = DocumentSource.WEB


def _parse(request: WebhookRequest) -> EventParseResult:  # noqa: ARG001
    return EventParseResult()


@pytest.fixture
def registered_event_source() -> Generator[None, None, None]:
    _SPECS.pop("input-type-test", None)
    register_webhook_source(
        WebhookSourceSpec(
            source=EVENT_SOURCE,
            slug="input-type-test",
            parser=_parse,
            verifier=None,
            allow_unsigned=True,
        )
    )
    try:
        yield
    finally:
        _SPECS.pop("input-type-test", None)


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
        db_session.delete(connector)
        db_session.commit()
