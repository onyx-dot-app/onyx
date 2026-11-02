"""A source that registers and then fails to import, for the loader test.

It claims all three registries a real source claims, so the loader's
rollback is tested against what a source actually leaves behind.
"""

from collections.abc import Mapping, Sequence

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox.handlers import register_event_handler
from onyx.connectors.event_inbox.models import WebhookRequest, WebhookSourceSpec
from onyx.connectors.event_inbox.source_registry import register_webhook_source
from onyx.connectors.event_models import EventParseResult
from onyx.connectors.models import Document
from onyx.context.search.enrichment.registry import register_enrichment_source
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


register_webhook_source(
    WebhookSourceSpec(
        source=SOURCE,
        slug="half-registered",
        parser=_parse,
        verifier=None,
        allow_unsigned=True,
    )
)
register_event_handler(SOURCE, _to_document)
register_enrichment_source(SOURCE, _allowed)

raise RuntimeError("this source fails after registering")
