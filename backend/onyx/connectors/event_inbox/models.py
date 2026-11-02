"""What a source declares to receive pushed events."""

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, model_validator

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_models import EventParseResult


class WebhookRequest(BaseModel):
    """One inbound delivery, decoupled from FastAPI. Raw bytes, because a
    signature covers exactly what the provider sent."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    raw_body: bytes
    headers: Mapping[str, str]
    # Which of the source's endpoints it arrived on, as the spec spells it.
    endpoint: str = ""


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
        """Answer a provider's endpoint-validation handshake, or None when
        the delivery is an ordinary event.

        Always runs after the signature check. A responder answers with the
        shared secret applied to input the caller chose, so on an unverified
        request it is a signing oracle: ask for the secret over the message
        a verifier would check, then replay the answer.
        """


class WebhookSourceSpec(BaseModel):
    """Everything the webhook server needs to serve one source."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    source: DocumentSource
    # The path segment under /webhook. Keep it stable: it is in the URL an
    # admin pastes into the provider's console.
    slug: str
    # Sub-paths under the slug, one per URL the provider posts to. The
    # parser reads `request.endpoint` to tell them apart.
    endpoints: tuple[str, ...] = ("",)
    parser: EventParser
    # No default: unauthenticated writes must be somebody's decision, not a
    # source's omission.
    verifier: SignatureVerifier | None
    # Grep for it to find every endpoint the internet can write to.
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
                "nothing. A responder applies the shared secret to input the "
                "caller chose, so with no signature to check first the "
                "endpoint is a signing oracle: ask it for the secret over the "
                "exact message a verifier would check, then replay the answer."
            )
        return self

    @model_validator(mode="after")
    def _slug_is_one_path_segment(self) -> "WebhookSourceSpec":
        """The slug is interpolated into a live URL, so it has to be one.

        `endpoints` carries the sub-paths; a slug holding a delimiter would
        serve a route somewhere other than where `webhook_callback_url` tells
        an admin to point the provider.
        """
        if not self.slug:
            raise ValueError("A webhook source needs a slug; it is in its URL.")
        bad = {character for character in "/?#%" if character in self.slug}
        if bad or self.slug.strip() != self.slug:
            raise ValueError(
                f"Webhook slug {self.slug!r} is not a single URL path "
                "segment. Put sub-paths in `endpoints` instead."
            )
        return self
