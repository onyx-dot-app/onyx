"""A source that registers and then fails to import, for the loader test."""

from collections.abc import Mapping, Sequence

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox.models import WebhookRequest, WebhookSourceSpec
from onyx.connectors.event_inbox.registration import register_event_source
from onyx.connectors.event_models import EventParseResult
from onyx.connectors.models import Document
from onyx.context.search.models import InferenceChunk
from onyx.db.models import ConnectorEventInbox

SOURCE = DocumentSource.WEB


def _parse(request: WebhookRequest) -> EventParseResult:  # noqa: ARG001
    return EventParseResult()


def _to_document(
    event: ConnectorEventInbox,  # noqa: ARG001
    secrets: Mapping[str, str],  # noqa: ARG001
) -> Document | None:
    return None


def _allowed(
    user_email: str,  # noqa: ARG001
    chunks: Sequence[InferenceChunk],  # noqa: ARG001
    secrets: Mapping[str, str],  # noqa: ARG001
) -> list[InferenceChunk]:
    return []


register_event_source(
    webhook=WebhookSourceSpec(
        source=SOURCE,
        slug="half-registered",
        parser=_parse,
        verifier=None,
        allow_unsigned=True,
    ),
    handler=_to_document,
    permission_filter=_allowed,
)

raise RuntimeError("this source fails after registering")
