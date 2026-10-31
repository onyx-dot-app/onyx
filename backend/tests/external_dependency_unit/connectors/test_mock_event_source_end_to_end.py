"""The pipeline end to end, through the paths production uses.

The other event tests build a spec in a fixture and call the drain
directly, which skips two joints: the loader that registers a source, and
the factory that picks the drain for an `EVENT` pair. This drives both.

A delivery arrives at the real webhook app, is verified, parsed and stored;
then a connector built the way `run_docfetching` builds one claims the rows
and yields the documents. Nothing here constructs a spec or a connector by
hand.
"""

import json
import sys
from collections.abc import Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from prometheus_client import CollectorRegistry
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy.orm import Session

from onyx.connectors.event_inbox import sources as sources_module
from onyx.connectors.event_inbox.connector import (
    EventInboxCheckpoint,
    EventInboxConnector,
)
from onyx.connectors.event_inbox.handlers import unregister_event_handler
from onyx.connectors.event_inbox.source_registry import (
    get_webhook_source,
    unregister_webhook_source,
    webhook_source_for,
)
from onyx.connectors.factory import instantiate_connector
from onyx.connectors.models import Document, InputType
from onyx.db.connector import create_connector
from onyx.db.connector_event_inbox import count_events_by_status
from onyx.db.enums import (
    AccessType,
    ConnectorCredentialPairStatus,
    ConnectorEventStatus,
)
from onyx.db.models import Connector, ConnectorCredentialPair, Credential, IndexAttempt
from onyx.server.documents.models import ConnectorBase
from tests.external_dependency_unit.connectors import mock_event_source

MODULE = "tests.external_dependency_unit.connectors.mock_event_source"
SECRET = "mock-webhook-secret"


@pytest.fixture
def loaded_source(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Register the source the way a deployment does, through the loader.

    Importing this module anywhere registers it, and this file imports it
    for its constants, so both the registration and the cached import are
    cleared first: otherwise the loader would be a no-op and the test would
    pass without it. A source registers once per process, so the cached
    module must go too.
    """
    owner = webhook_source_for(mock_event_source.SOURCE)
    if owner is not None:
        unregister_webhook_source(owner.slug)
    unregister_event_handler(mock_event_source.SOURCE)
    sys.modules.pop(MODULE, None)

    monkeypatch.setattr(sources_module, "_loaded", False)
    monkeypatch.setattr(sources_module, "EVENT_SOURCE_MODULES", (MODULE,))
    sources_module.load_event_sources()
    try:
        yield
    finally:
        unregister_webhook_source(mock_event_source.SLUG)
        unregister_event_handler(mock_event_source.SOURCE)
        sys.modules.pop(MODULE, None)


@pytest.fixture
def client(loaded_source: None) -> TestClient:  # noqa: ARG001
    """The real webhook app, with a throwaway metrics registry.

    The instrumentator registers on the global one when the middleware
    stack is built, so sharing it with another instrumented test raises on
    duplicate timeseries.
    """
    from onyx.webhook_server import api as webhook_api

    isolated = Instrumentator(registry=CollectorRegistry())
    with patch.object(
        webhook_api, "create_prometheus_instrumentator", return_value=isolated
    ):
        app = webhook_api.create_webhook_app()
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def event_pair(
    db_session: Session,
    loaded_source: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    """A pair created the way the admin API creates one.

    `input_type` is deliberately POLL here: the backend decides it from the
    registry, and this proves it.
    """
    created = create_connector(
        db_session=db_session,
        connector_data=ConnectorBase(
            name="mock-event-source",
            source=mock_event_source.SOURCE,
            input_type=InputType.POLL,
            # A real event pair carries the source's settings. They are not
            # the drain's: with a non-empty config, building the source's
            # connector from them would fail, which is what makes the
            # factory's event branch load-bearing.
            connector_specific_config={
                "mock_server_host": "localhost",
                "mock_server_port": 8080,
            },
            refresh_freq=None,
            prune_freq=None,
            indexing_start=None,
        ),
    )
    connector = db_session.query(Connector).filter_by(id=created.id).one()
    credential = Credential(
        credential_json={mock_event_source.SECRET_FIELD: SECRET},
        source=mock_event_source.SOURCE,
        admin_public=True,
    )
    db_session.add(credential)
    db_session.flush()
    pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=f"mock-event-pair-{connector.id}",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
        total_docs_indexed=0,
    )
    db_session.add(pair)
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


def _deliver(client: TestClient, body: dict, secret: str = SECRET) -> Response:
    raw = json.dumps(body)
    return client.post(
        f"/{mock_event_source.SLUG}",
        content=raw,
        headers={
            mock_event_source.SIGNATURE_HEADER: mock_event_source.sign(raw, secret)
        },
    )


def _drain_through_the_factory(
    db_session: Session, pair: ConnectorCredentialPair
) -> list[Document]:
    """Build the connector the way `run_docfetching` does, then drain."""
    attempt = IndexAttempt(
        connector_credential_pair_id=pair.id,
        from_beginning=False,
        status="in_progress",
    )
    db_session.add(attempt)
    db_session.commit()

    connector = instantiate_connector(
        db_session=db_session,
        source=pair.connector.source,
        input_type=pair.connector.input_type,
        connector_specific_config=pair.connector.connector_specific_config,
        credential=pair.credential,
    )
    assert isinstance(connector, EventInboxConnector)
    connector.set_event_context(cc_pair_id=pair.id, index_attempt_id=attempt.id)

    documents: list[Document] = []
    generator = connector.load_from_checkpoint(
        0, 0, EventInboxCheckpoint(has_more=True)
    )
    while True:
        try:
            item = next(generator)
        except StopIteration:
            return documents
        if isinstance(item, Document):
            documents.append(item)


def test_the_loader_is_what_registers_the_source(loaded_source: None) -> None:  # noqa: ARG001
    """Not the test's own import: the fixture clears both first."""
    assert get_webhook_source(mock_event_source.SLUG) is not None


def test_the_pair_is_created_as_an_event_pair(
    event_pair: ConnectorCredentialPair,
) -> None:
    """The caller asked for POLL; the registry decides."""
    assert event_pair.connector.input_type == InputType.EVENT


def test_a_delivery_becomes_a_searchable_document(
    client: TestClient,
    db_session: Session,
    event_pair: ConnectorCredentialPair,
) -> None:
    response = _deliver(
        client,
        {
            "delivery": "d-1",
            "changes": [
                {"kind": "updated", "id": "doc-1", "title": "First"},
                {"kind": "updated", "id": "doc-2", "title": "Second"},
                {"kind": "ignored", "id": "doc-3"},
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"accepted": 2, "duplicates": 0, "ignored": 1}

    documents = _drain_through_the_factory(db_session, event_pair)

    assert sorted(document.id for document in documents) == ["doc-1", "doc-2"]
    assert sorted(d.semantic_identifier for d in documents) == ["First", "Second"]
    assert count_events_by_status(db_session, event_pair.id) == {
        ConnectorEventStatus.IN_PROGRESS: 2
    }


def test_a_delete_reaches_the_queue_but_yields_no_document(
    client: TestClient,
    db_session: Session,
    event_pair: ConnectorCredentialPair,
) -> None:
    _deliver(
        client,
        {"delivery": "d-2", "changes": [{"kind": "removed", "id": "doc-gone"}]},
    )

    documents = _drain_through_the_factory(db_session, event_pair)

    assert documents == []
    assert count_events_by_status(db_session, event_pair.id) == {
        ConnectorEventStatus.IN_PROGRESS: 1
    }


def test_the_providers_retry_indexes_the_document_once(
    client: TestClient,
    db_session: Session,
    event_pair: ConnectorCredentialPair,
) -> None:
    body = {
        "delivery": "d-3",
        "changes": [{"kind": "updated", "id": "doc-1", "title": "Only once"}],
    }
    assert _deliver(client, body).status_code == 200
    assert _deliver(client, body).json() == {
        "accepted": 0,
        "duplicates": 1,
        "ignored": 0,
    }

    documents = _drain_through_the_factory(db_session, event_pair)

    assert [document.id for document in documents] == ["doc-1"]


def test_an_unsigned_delivery_reaches_neither_the_queue_nor_the_index(
    client: TestClient,
    db_session: Session,
    event_pair: ConnectorCredentialPair,
) -> None:
    response = _deliver(
        client,
        {"delivery": "d-4", "changes": [{"kind": "updated", "id": "forged"}]},
        secret="not-the-secret",
    )

    assert response.status_code == 401
    assert count_events_by_status(db_session, event_pair.id) == {}
    assert _drain_through_the_factory(db_session, event_pair) == []


def test_health_still_answers_while_a_source_is_registered(
    client: TestClient,
) -> None:
    """The probes share the app with the source's route."""
    assert client.get("/health").status_code == 200
