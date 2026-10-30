"""A source that registers at import, for the loader test.

Also the smallest complete example of the contract: one spec, registered
when the module is imported.
"""

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox.source_registry import (
    WebhookRequest,
    WebhookSourceSpec,
    register_webhook_source,
)
from onyx.connectors.event_models import EventParseResult


def _parse(request: WebhookRequest) -> EventParseResult:  # noqa: ARG001
    return EventParseResult()


register_webhook_source(
    WebhookSourceSpec(
        source=DocumentSource.MOCK_CONNECTOR,
        slug="registering-source",
        parser=_parse,
        verifier=None,
        allow_unsigned=True,
    )
)
