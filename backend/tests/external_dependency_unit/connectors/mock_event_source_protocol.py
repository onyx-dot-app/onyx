"""The mock event source's protocol: a signed, batched body with an ignored
event type and a delete. Registers nothing, so tests can import it freely;
`mock_event_source` registers it."""

import hashlib
import hmac
import json
from collections.abc import Mapping

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox.models import WebhookRequest
from onyx.connectors.event_models import EventParseResult, ParsedEvent
from onyx.connectors.models import Document, TextSection
from onyx.db.enums import ConnectorEventType
from onyx.db.models import ConnectorEventInbox
from onyx.webhook_server.exceptions import WebhookAuthError, WebhookPayloadError

SOURCE = DocumentSource.MOCK_CONNECTOR
SLUG = "mock-events"
SECRET_FIELD = "webhook_secret"
SIGNATURE_HEADER = "x-mock-signature"


def sign(body: str, secret: str) -> str:
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def verify(request: WebhookRequest, secrets: Mapping[str, str]) -> None:
    secret = secrets.get(SECRET_FIELD)
    if not secret:
        raise WebhookAuthError("no webhook secret on the credential")

    presented = request.headers.get(SIGNATURE_HEADER, "")
    if not hmac.compare_digest(sign(request.raw_body.decode(), secret), presented):
        raise WebhookAuthError("signature mismatch")


def parse(request: WebhookRequest) -> EventParseResult:
    try:
        body = json.loads(request.raw_body)
    except json.JSONDecodeError as e:
        raise WebhookPayloadError(f"body is not JSON: {e}")

    events: list[ParsedEvent] = []
    ignored = 0
    for change in body["changes"]:
        if change["kind"] not in ("updated", "removed"):
            ignored += 1
            continue
        events.append(
            ParsedEvent(
                document_id=change["id"],
                event_type=(
                    ConnectorEventType.DELETE
                    if change["kind"] == "removed"
                    else ConnectorEventType.UPSERT
                ),
                event_key=body["delivery"],
                payload={"title": change.get("title")},
            )
        )
    return EventParseResult(events=events, ignored=ignored)


def to_document(
    event: ConnectorEventInbox,
    secrets: Mapping[str, str],  # noqa: ARG001
) -> Document | None:
    if event.event_type == ConnectorEventType.DELETE:
        return None

    payload = event.payload if isinstance(event.payload, Mapping) else {}
    title = payload.get("title")
    return Document(
        id=event.document_id,
        source=SOURCE,
        semantic_identifier=title if isinstance(title, str) else event.document_id,
        metadata={},
        sections=[TextSection(text=f"body of {event.document_id}", link=None)],
    )
