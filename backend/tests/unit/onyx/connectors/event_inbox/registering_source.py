"""The smallest source: one `register_event_source` call at import."""

from collections.abc import Mapping

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox.models import WebhookRequest, WebhookSourceSpec
from onyx.connectors.event_inbox.registration import register_event_source
from onyx.connectors.event_models import EventParseResult
from onyx.connectors.models import Document
from onyx.db.models import ConnectorEventInbox


def _parse(request: WebhookRequest) -> EventParseResult:  # noqa: ARG001
    return EventParseResult()


def _to_document(
    event: ConnectorEventInbox,  # noqa: ARG001
    secrets: Mapping[str, str],  # noqa: ARG001
) -> Document | None:
    return None


register_event_source(
    webhook=WebhookSourceSpec(
        source=DocumentSource.MOCK_CONNECTOR,
        slug="registering-source",
        parser=_parse,
        verifier=None,
        allow_unsigned=True,
    ),
    handler=_to_document,
)
