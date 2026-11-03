"""What a source declares to receive pushed events."""

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, model_validator

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_models import EventParseResult
from onyx.connectors.models import Document
from onyx.db.models import ConnectorEventInbox


class WebhookRequest(BaseModel):
    """One inbound delivery, decoupled from FastAPI. Raw bytes, because a
    signature covers exactly what the provider sent."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    raw_body: bytes
    headers: Mapping[str, str]
    endpoint: str = ""


# runtime_checkable so Pydantic can hold these as fields.
@runtime_checkable
class EventParser(Protocol):
    def __call__(self, request: WebhookRequest) -> EventParseResult:
        """Raise `WebhookPayloadError` for a body this source cannot read."""


@runtime_checkable
class SignatureVerifier(Protocol):
    def __call__(self, request: WebhookRequest, secrets: Mapping[str, str]) -> None:
        """Raise `WebhookAuthError` unless the source sent the delivery.
        `secrets` is the pair's decrypted credential JSON."""


@runtime_checkable
class ChallengeResponder(Protocol):
    def __call__(
        self, request: WebhookRequest, secrets: Mapping[str, str]
    ) -> dict[str, object] | None:
        """Answer an endpoint-validation handshake, or None for an ordinary
        event. Runs only after the signature check: on an unverified request
        a responder is a signing oracle."""


class WebhookSourceSpec(BaseModel):
    """Everything the webhook server needs to serve one source."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    source: DocumentSource
    # Keep it stable: admins paste the URL into the provider's console.
    slug: str
    endpoints: tuple[str, ...] = ("",)
    parser: EventParser
    # No default, so an unsigned source is a decision, not an omission.
    verifier: SignatureVerifier | None
    allow_unsigned: bool = False
    challenge_responder: ChallengeResponder | None = None

    @model_validator(mode="after")
    def _endpoints_are_paths(self) -> "WebhookSourceSpec":
        if not self.endpoints:
            raise ValueError(
                f"Webhook source {self.slug} declares no endpoints. Leave the "
                'default ("",) to serve the slug itself.'
            )
        if len(set(self.endpoints)) != len(self.endpoints):
            raise ValueError(
                f"Webhook source {self.slug} repeats an endpoint. Two routes "
                "on one path would shadow each other."
            )
        for endpoint in self.endpoints:
            if endpoint and not endpoint.startswith("/"):
                raise ValueError(
                    f"Webhook endpoint {endpoint!r} of {self.slug} must start "
                    'with "/" or be "".'
                )
            if any(character in endpoint for character in "?#%"):
                raise ValueError(
                    f"Webhook endpoint {endpoint!r} of {self.slug} holds a "
                    "URL delimiter, so it would serve a different path than "
                    "the one an admin pastes into the provider."
                )
            if endpoint.endswith("/"):
                raise ValueError(
                    f"Webhook endpoint {endpoint!r} of {self.slug} ends with "
                    '"/", which serves a different URL than the one an admin '
                    "pastes into the provider."
                )
        return self

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
        if self.allow_unsigned and self.challenge_responder is not None:
            raise ValueError(
                f"Webhook source {self.slug} answers a handshake but signs "
                "nothing, which makes the endpoint a signing oracle."
            )
        return self

    @model_validator(mode="after")
    def _slug_is_one_path_segment(self) -> "WebhookSourceSpec":
        if not self.slug:
            raise ValueError("A webhook source needs a slug; it is in its URL.")
        bad = {character for character in "/?#%" if character in self.slug}
        if bad or self.slug.strip() != self.slug:
            raise ValueError(
                f"Webhook slug {self.slug!r} is not a single URL path "
                "segment. Put sub-paths in `endpoints` instead."
            )
        return self


@runtime_checkable
class EventHandler(Protocol):
    """Turns one stored event into the document it describes."""

    def __call__(
        self, event: ConnectorEventInbox, secrets: Mapping[str, str]
    ) -> Document | None:
        """Return the document, or None to index nothing. `secrets` is the
        pair's credential, for a provider that pushes a link to the body.
        Raising retries this row alone."""
