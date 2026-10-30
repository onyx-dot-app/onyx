"""The seam a new event source plugs into, proven end to end.

A source supplies a spec and a handler and gets the rest: an endpoint, the
pair lookup that opens and closes it, signature rejection, storage, and the
drain that turns stored rows into documents. This test is the template a
real source follows, and it is what tells us the plumbing works before any
real source exists.
"""

import json
from collections.abc import Generator, Mapping

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox.connector import (
    EventInboxCheckpoint,
    EventInboxConnector,
)
from onyx.connectors.event_inbox.handlers import _HANDLERS, register_event_handler
from onyx.connectors.event_inbox.source_registry import (
    _SPECS,
    WebhookRequest,
    WebhookSourceSpec,
    register_webhook_source,
)
from onyx.connectors.event_models import EventParseResult, ParsedEvent
from onyx.connectors.models import Document, InputType, TextSection
from onyx.db.connector_event_inbox import count_events_by_status
from onyx.db.enums import (
    AccessType,
    ConnectorCredentialPairStatus,
    ConnectorEventStatus,
)
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    ConnectorEventInbox,
    Credential,
    IndexAttempt,
)
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.webhook_server.exceptions import WebhookAuthError
from onyx.webhook_server.routes import build_webhook_router

SOURCE = DocumentSource.MOCK_CONNECTOR
SLUG = "pipeline-test"
SECRET = "shared-secret"


def _verifier(request: WebhookRequest, secrets: Mapping[str, str]) -> None:
    if request.headers.get("x-test-signature") != secrets.get("webhook_secret"):
        raise WebhookAuthError("bad signature")


def _parser(request: WebhookRequest) -> EventParseResult:
    body = json.loads(request.raw_body)
    return EventParseResult(
        events=[
            ParsedEvent(document_id=item["id"], event_key=item["delivery"])
            for item in body["changed"]
        ],
        ignored=body.get("ignored", 0),
    )


def _handler(event: ConnectorEventInbox) -> Document:
    return Document(
        id=event.document_id,
        source=SOURCE,
        semantic_identifier=event.document_id,
        metadata={},
        sections=[TextSection(text="body", link=None)],
    )


@pytest.fixture(autouse=True)
def registered_source() -> Generator[None, None, None]:
    register_webhook_source(
        WebhookSourceSpec(source=SOURCE, slug=SLUG, parser=_parser, verifier=_verifier)
    )
    register_event_handler(SOURCE, _handler)
    try:
        yield
    finally:
        _SPECS.pop(SLUG, None)
        _HANDLERS.pop(SOURCE, None)


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.include_router(build_webhook_router())
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def event_pair(db_session: Session) -> Generator[ConnectorCredentialPair, None, None]:
    connector = Connector(
        name="pipeline-connector",
        source=SOURCE,
        input_type=InputType.EVENT,
        connector_specific_config={},
    )
    credential = Credential(
        credential_json={"webhook_secret": SECRET}, source=SOURCE, admin_public=True
    )
    db_session.add_all([connector, credential])
    db_session.flush()
    pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=f"pipeline-pair-{connector.id}",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
        total_docs_indexed=0,
    )
    db_session.add(pair)
    db_session.commit()
    try:
        yield pair
    finally:
        # A failed test leaves the session unusable, and the deletes below
        # would then raise and mask it.
        db_session.rollback()
        db_session.query(IndexAttempt).filter_by(
            connector_credential_pair_id=pair.id
        ).delete()
        db_session.delete(pair)
        db_session.delete(connector)
        db_session.delete(credential)
        db_session.commit()


def _route_paths(app: FastAPI) -> set[str]:
    return {route.path for route in app.routes if isinstance(route, APIRoute)}


def _post(client: TestClient, body: dict, signature: str = SECRET) -> Response:
    return client.post(
        f"/{SLUG}", content=json.dumps(body), headers={"x-test-signature": signature}
    )


def test_endpoint_is_closed_until_a_connector_is_set_up(
    client: TestClient,
    db_session: Session,  # noqa: ARG001 - initializes SqlEngine for the route
) -> None:
    """Setting the connector up is what opens the endpoint."""
    response = _post(client, {"changed": [{"id": "d1", "delivery": "k1"}]})
    assert response.status_code == 404


def test_a_signed_delivery_is_stored(
    client: TestClient,
    db_session: Session,
    event_pair: ConnectorCredentialPair,
) -> None:
    response = _post(
        client,
        {
            "changed": [
                {"id": "doc-1", "delivery": "k-1"},
                {"id": "doc-2", "delivery": "k-2"},
            ],
            "ignored": 1,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"accepted": 2, "duplicates": 0, "ignored": 1}
    assert count_events_by_status(db_session, event_pair.id) == {
        ConnectorEventStatus.PENDING: 2
    }


def test_a_redelivery_is_accepted_but_stored_once(
    client: TestClient,
    db_session: Session,
    event_pair: ConnectorCredentialPair,
) -> None:
    body = {"changed": [{"id": "doc-1", "delivery": "k-1"}]}
    assert _post(client, body).status_code == 200
    second = _post(client, body)

    # 200, not an error: the provider has nothing to fix, and a retry would
    # only write the same conflict again.
    assert second.status_code == 200
    assert second.json() == {"accepted": 0, "duplicates": 1, "ignored": 0}
    assert count_events_by_status(db_session, event_pair.id) == {
        ConnectorEventStatus.PENDING: 1
    }


def test_an_unsigned_delivery_writes_nothing(
    client: TestClient,
    db_session: Session,
    event_pair: ConnectorCredentialPair,
) -> None:
    response = _post(
        client,
        {"changed": [{"id": "doc-1", "delivery": "k-1"}]},
        signature="wrong",
    )

    assert response.status_code == 401
    assert count_events_by_status(db_session, event_pair.id) == {}


def test_a_delivery_becomes_a_document_on_the_next_run(
    client: TestClient,
    db_session: Session,
    event_pair: ConnectorCredentialPair,
) -> None:
    """The whole chain: POST, store, drain, document."""
    _post(
        client,
        {"changed": [{"id": "doc-1", "delivery": "k-1"}]},
    )

    attempt = IndexAttempt(
        connector_credential_pair_id=event_pair.id,
        from_beginning=False,
        status="in_progress",
    )
    db_session.add(attempt)
    db_session.commit()

    connector = EventInboxConnector(batch_size=10)
    connector.set_event_context(cc_pair_id=event_pair.id, index_attempt_id=attempt.id)
    documents: list[Document] = []
    generator = connector.load_from_checkpoint(
        0, 0, EventInboxCheckpoint(has_more=True)
    )
    while True:
        try:
            item = next(generator)
        except StopIteration:
            break
        if isinstance(item, Document):
            documents.append(item)

    assert [document.id for document in documents] == ["doc-1"]
    # Claimed, not completed: the row settles on this attempt's outcome.
    assert count_events_by_status(db_session, event_pair.id) == {
        ConnectorEventStatus.IN_PROGRESS: 1
    }


def test_the_factory_runs_the_drain_for_an_event_pair() -> None:
    """Without this the pair would run the source's own connector and the
    queue would never be read."""
    from onyx.connectors.factory import identify_connector_class

    assert identify_connector_class(SOURCE, InputType.EVENT) is EventInboxConnector


def test_the_route_refuses_a_spec_with_no_verifier(
    db_session: Session,  # noqa: ARG001 - initializes SqlEngine for the route
    event_pair: ConnectorCredentialPair,
) -> None:
    """Defence in depth: the write path does not rely on the spec validator
    having run, because a spec built another way would bypass it."""
    unsigned = WebhookSourceSpec(
        source=SOURCE, slug=SLUG, parser=_parser, verifier=None, allow_unsigned=True
    )
    # Reproduce the state the validator forbids.
    object.__setattr__(unsigned, "allow_unsigned", False)
    _SPECS.pop(SLUG, None)
    register_webhook_source(unsigned)

    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.include_router(build_webhook_router())
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(f"/{SLUG}", content=json.dumps({"changed": []}))

    assert response.status_code == 401
    assert count_events_by_status(db_session, event_pair.id) == {}
