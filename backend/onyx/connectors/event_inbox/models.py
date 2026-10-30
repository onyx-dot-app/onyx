"""What a source declares to receive pushed events.

A source supplies one `WebhookSourceSpec`; the registry in
`source_registry.py` holds them and the webhook server builds a route per
spec.
"""

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, model_validator

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_models import EventParseResult


class WebhookRequest(BaseModel):
    """One inbound delivery, decoupled from FastAPI.

    Carries the raw body as well as the decoded one: a signature covers the
    exact bytes the provider sent, and re-serializing the parsed JSON can
    change them.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    raw_body: bytes
    headers: Mapping[str, str]


# runtime_checkable so the spec below can hold these as Pydantic fields.
@runtime_checkable
class EventParser(Protocol):
    def __call__(self, request: WebhookRequest) -> EventParseResult:
        """Turn one delivery into the changes it reports.

        Raise `WebhookPayloadError` for a body this source cannot read.
        """


@runtime_checkable
class SignatureVerifier(Protocol):
    def __call__(self, request: WebhookRequest, secrets: Mapping[str, str]) -> None:
        """Raise `WebhookAuthError` unless the delivery is genuinely from the
        source. `secrets` is the pair's decrypted credential JSON."""


@runtime_checkable
class ChallengeResponder(Protocol):
    def __call__(
        self, request: WebhookRequest, secrets: Mapping[str, str]
    ) -> dict[str, object] | None:
        """Answer a provider's endpoint-validation handshake.

        Several providers (Zoom among them) prove an endpoint is theirs by
        POSTing a challenge to it before they will save it. Returning a body
        answers the handshake; returning None means this delivery is an
        ordinary event.

        Always runs after the signature check. A responder usually answers
        with a value derived from the shared secret, so running it on an
        unverified request would hand an attacker a signing oracle: they
        choose the challenge, read back the secret applied to it, and forge
        any event they like.
        """


class WebhookSourceSpec(BaseModel):
    """Everything the webhook server needs to serve one source."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    source: DocumentSource
    # The path segment under /webhook, so a Zoom spec with slug "zoom" is
    # reached at /webhook/zoom. Keep it stable: it is in the URL an admin
    # pastes into the provider's console.
    slug: str
    parser: EventParser
    # No default: an endpoint that takes unauthenticated writes must be a
    # decision somebody made, not one a source reached by omission.
    verifier: SignatureVerifier | None
    # The deliberate escape hatch for a provider that signs nothing. Grep for
    # it to find every endpoint the internet can write to.
    allow_unsigned: bool = False
    challenge_responder: ChallengeResponder | None = None

    @model_validator(mode="after")
    def _signing_is_decided(self) -> "WebhookSourceSpec":
        if self.verifier is None and not self.allow_unsigned:
            raise ValueError(
                f"Webhook source {self.slug} has no verifier. Anyone who finds "
                "the URL could write to the event inbox. Supply a verifier, or "
                "set allow_unsigned=True if the provider signs nothing."
            )
        if self.verifier is not None and self.allow_unsigned:
            raise ValueError(
                f"Webhook source {self.slug} sets allow_unsigned with a "
                "verifier. Drop one so the intent is unambiguous."
            )
        return self
