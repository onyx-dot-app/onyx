"""Can a real provider be wired up with what the framework gives?

This builds a source against Zoom's actual webhook protocol — its
`endpoint.url_validation` handshake, its `v0:timestamp:body` HMAC header, and
a `recording.completed` payload — without using anything Zoom-specific in the
framework. If a provider this fiddly fits, the seams are the right shape; if
it does not, this test is where that shows up before a real source is written.

It is a test, not a Zoom connector: it proves the framework, and it is the
worked example a real source copies.
"""

import hashlib
import hmac
import json
import time
from collections.abc import Generator, Mapping
from typing import Any

import pytest
from fastapi import FastAPI
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
from onyx.webhook_server.exceptions import WebhookAuthError, WebhookPayloadError
from onyx.webhook_server.routes import build_webhook_router

# Stands in for DocumentSource.ZOOM so the test owns no real source.
SOURCE = DocumentSource.MOCK_CONNECTOR
SLUG = "zoomlike"
SECRET_TOKEN = "zoom-secret-token"


# --------------------------------------------------------------------------
# Everything below is what a real source author writes. One file.
# --------------------------------------------------------------------------


def verify(request: WebhookRequest, secrets: Mapping[str, str]) -> None:
    """Zoom signs `v0:<timestamp>:<body>` with the secret token."""
    token = secrets.get("webhook_secret_token")
    if not token:
        raise WebhookAuthError("no secret token on the credential")

    timestamp = request.headers.get("x-zm-request-timestamp")
    signature = request.headers.get("x-zm-signature")
    if not timestamp or not signature:
        raise WebhookAuthError("missing signature headers")

    message = f"v0:{timestamp}:{request.raw_body.decode()}"
    expected = (
        "v0=" + hmac.new(token.encode(), message.encode(), hashlib.sha256).hexdigest()
    )
    if not hmac.compare_digest(expected, signature):
        raise WebhookAuthError("signature mismatch")


def answer_challenge(
    request: WebhookRequest, secrets: Mapping[str, str]
) -> dict[str, object] | None:
    """Zoom will not save an endpoint until it answers this handshake."""
    body = json.loads(request.raw_body)
    if body.get("event") != "endpoint.url_validation":
        return None

    plain = body["payload"]["plainToken"]
    token = secrets["webhook_secret_token"]
    encrypted = hmac.new(token.encode(), plain.encode(), hashlib.sha256).hexdigest()
    return {"plainToken": plain, "encryptedToken": encrypted}


def parse(request: WebhookRequest) -> EventParseResult:
    try:
        body = json.loads(request.raw_body)
    except json.JSONDecodeError as e:
        raise WebhookPayloadError(f"body is not JSON: {e}")

    if body.get("event") != "recording.completed":
        # A subscription usually delivers more event types than a source
        # indexes; counting them keeps a 200 honest.
        return EventParseResult(ignored=1)

    recording = body["payload"]["object"]
    return EventParseResult(
        events=[
            ParsedEvent(
                document_id=f"zoom-meeting-{recording['uuid']}",
                event_key=str(body["event_ts"]),
                payload={
                    "topic": recording["topic"],
                    "download_token": body.get("download_token"),
                },
            )
        ]
    )


def to_document(event: ConnectorEventInbox) -> Document:
    payload: Any = event.payload or {}
    return Document(
        id=event.document_id,
        source=SOURCE,
        semantic_identifier=payload.get("topic", event.document_id),
        metadata={},
        sections=[TextSection(text="transcript text", link=None)],
    )


SPEC = WebhookSourceSpec(
    source=SOURCE,
    slug=SLUG,
    parser=parse,
    verifier=verify,
    # Zoom signs the handshake with the same header as an event, so it
    # verifies before it is answered, like everything else.
    challenge_responder=answer_challenge,
)


# --------------------------------------------------------------------------
# The exercise.
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def registered() -> Generator[None, None, None]:
    register_webhook_source(SPEC)
    register_event_handler(SOURCE, to_document)
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
def pair(db_session: Session) -> Generator[ConnectorCredentialPair, None, None]:
    connector = Connector(
        name="zoomlike",
        source=SOURCE,
        input_type=InputType.EVENT,
        connector_specific_config={},
    )
    credential = Credential(
        credential_json={"webhook_secret_token": SECRET_TOKEN},
        source=SOURCE,
        admin_public=True,
    )
    db_session.add_all([connector, credential])
    db_session.flush()
    cc_pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=f"zoomlike-{connector.id}",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
        total_docs_indexed=0,
    )
    db_session.add(cc_pair)
    db_session.commit()
    try:
        yield cc_pair
    finally:
        # A failed test leaves the session unusable, and the deletes below
        # would then raise and mask it.
        db_session.rollback()
        db_session.query(IndexAttempt).filter_by(
            connector_credential_pair_id=cc_pair.id
        ).delete()
        db_session.delete(cc_pair)
        db_session.delete(connector)
        db_session.delete(credential)
        db_session.commit()


def _signed_post(client: TestClient, body: dict, token: str = SECRET_TOKEN) -> Response:
    raw = json.dumps(body)
    timestamp = str(int(time.time()))
    signature = (
        "v0="
        + hmac.new(
            token.encode(), f"v0:{timestamp}:{raw}".encode(), hashlib.sha256
        ).hexdigest()
    )
    return client.post(
        f"/{SLUG}",
        content=raw,
        headers={
            "x-zm-request-timestamp": timestamp,
            "x-zm-signature": signature,
        },
    )


def _recording(uuid: str, event_ts: int) -> dict:
    return {
        "event": "recording.completed",
        "event_ts": event_ts,
        "download_token": "dl-token",
        "payload": {"object": {"uuid": uuid, "topic": "Quarterly review"}},
    }


def test_the_provider_can_register_its_endpoint(
    client: TestClient,
    db_session: Session,  # noqa: ARG001 - initializes SqlEngine for the route
    pair: ConnectorCredentialPair,  # noqa: ARG001 - the endpoint needs an active pair
) -> None:
    """Zoom refuses to save an endpoint that cannot answer this."""
    response = _signed_post(
        client,
        {
            "event": "endpoint.url_validation",
            "payload": {"plainToken": "abc123"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plainToken"] == "abc123"
    assert (
        body["encryptedToken"]
        == hmac.new(SECRET_TOKEN.encode(), b"abc123", hashlib.sha256).hexdigest()
    )


def test_a_recording_becomes_a_searchable_document(
    client: TestClient,
    db_session: Session,
    pair: ConnectorCredentialPair,
) -> None:
    assert _signed_post(client, _recording("uuid-1", 1700000000)).status_code == 200

    attempt = IndexAttempt(
        connector_credential_pair_id=pair.id,
        from_beginning=False,
        status="in_progress",
    )
    db_session.add(attempt)
    db_session.commit()

    connector = EventInboxConnector(batch_size=10)
    connector.set_event_context(cc_pair_id=pair.id, index_attempt_id=attempt.id)
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

    assert [document.id for document in documents] == ["zoom-meeting-uuid-1"]
    # The parser's payload survived to the handler.
    assert documents[0].semantic_identifier == "Quarterly review"
    # Claimed, not completed: the row settles on this attempt's outcome.
    assert count_events_by_status(db_session, pair.id) == {
        ConnectorEventStatus.IN_PROGRESS: 1
    }


def test_an_event_type_the_source_ignores_still_answers_200(
    client: TestClient,
    db_session: Session,
    pair: ConnectorCredentialPair,
) -> None:
    """A subscription delivers more than a source indexes. Answering 4xx
    would make the provider retry something it should drop."""
    response = _signed_post(
        client, {"event": "meeting.started", "event_ts": 1, "payload": {}}
    )

    assert response.status_code == 200
    assert response.json() == {"accepted": 0, "duplicates": 0, "ignored": 1}
    assert count_events_by_status(db_session, pair.id) == {}


def test_a_forged_delivery_is_refused(
    client: TestClient,
    db_session: Session,
    pair: ConnectorCredentialPair,
) -> None:
    response = _signed_post(
        client, _recording("uuid-1", 1700000000), token="not-the-token"
    )

    assert response.status_code == 401
    assert count_events_by_status(db_session, pair.id) == {}


def test_the_providers_retry_does_not_double_index(
    client: TestClient,
    db_session: Session,
    pair: ConnectorCredentialPair,
) -> None:
    """Zoom retries until it gets a 2xx, so the same event_ts can arrive
    several times."""
    body = _recording("uuid-1", 1700000000)
    assert _signed_post(client, body).status_code == 200
    assert _signed_post(client, body).status_code == 200

    assert count_events_by_status(db_session, pair.id) == {
        ConnectorEventStatus.PENDING: 1
    }


def test_an_unreadable_body_is_rejected_not_stored(
    client: TestClient,
    db_session: Session,
    pair: ConnectorCredentialPair,
) -> None:
    raw = "{not json"
    timestamp = str(int(time.time()))
    signature = (
        "v0="
        + hmac.new(
            SECRET_TOKEN.encode(),
            f"v0:{timestamp}:{raw}".encode(),
            hashlib.sha256,
        ).hexdigest()
    )
    response = client.post(
        f"/{SLUG}",
        content=raw,
        headers={
            "x-zm-request-timestamp": timestamp,
            "x-zm-signature": signature,
        },
    )

    assert response.status_code == 400
    assert count_events_by_status(db_session, pair.id) == {}


def test_a_parser_that_reaches_into_a_missing_field_is_contained(
    client: TestClient,
    db_session: Session,
    pair: ConnectorCredentialPair,
) -> None:
    """Source code raises; the route must not answer 5xx for it.

    A 500 tells the provider to retry, and it will keep retrying a body that
    will never parse. This parser does `body["payload"]["object"]`, which is
    what a source author naturally writes.
    """
    response = _signed_post(
        client,
        {"event": "recording.completed", "event_ts": 1, "payload": {}},
    )

    assert response.status_code == 400
    assert count_events_by_status(db_session, pair.id) == {}


def test_a_verifier_that_raises_fails_closed(
    db_session: Session,
    pair: ConnectorCredentialPair,
) -> None:
    """An exception proves nothing, so it must not read as proof."""

    def exploding_verifier(request: WebhookRequest, secrets: Mapping[str, str]) -> None:  # noqa: ARG001
        raise RuntimeError("the verifier has a bug")

    # Register before building: a router captures the specs it was built
    # from, so a later registration does not reach an existing app. The slug
    # is already claimed, and a registry refuses a duplicate.
    _SPECS.pop(SLUG, None)
    register_webhook_source(SPEC.model_copy(update={"verifier": exploding_verifier}))
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.include_router(build_webhook_router())
    broken_client = TestClient(app, raise_server_exceptions=False)

    response = _signed_post(broken_client, _recording("uuid-1", 1700000000))

    assert response.status_code == 401
    assert count_events_by_status(db_session, pair.id) == {}


def test_the_handshake_cannot_be_used_to_sign_arbitrary_content(
    client: TestClient,
    db_session: Session,
    pair: ConnectorCredentialPair,
) -> None:
    """A responder that runs before verification is a signing oracle.

    Zoom's handshake answers HMAC(secret, plainToken) to an unauthenticated
    caller. If that runs before the signature check, an attacker sets
    plainToken to the exact message the verifier signs and reads back a
    valid signature, which forges any event they like.
    """
    raw = json.dumps(_recording("forged-uuid", 1700000001))
    timestamp = "1700000001"

    # The attacker knows the signing scheme, not the secret.
    oracle = client.post(
        f"/{SLUG}",
        content=json.dumps(
            {
                "event": "endpoint.url_validation",
                "payload": {"plainToken": f"v0:{timestamp}:{raw}"},
            }
        ),
        headers={"x-zm-request-timestamp": timestamp, "x-zm-signature": "v0=junk"},
    )

    assert oracle.status_code == 401, (
        "an unauthenticated caller reached the handshake and can now read "
        "back a signature over content of their choosing"
    )
    assert count_events_by_status(db_session, pair.id) == {}
