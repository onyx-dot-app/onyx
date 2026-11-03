"""A mock event source that registers at import, the way a real one does
when the loader names it in `EVENT_SOURCE_MODULES`."""

from onyx.connectors.event_inbox.handlers import register_event_handler
from onyx.connectors.event_inbox.models import WebhookSourceSpec
from onyx.connectors.event_inbox.source_registry import register_webhook_source
from tests.external_dependency_unit.connectors.mock_event_source_protocol import (
    SLUG,
    SOURCE,
    parse,
    to_document,
    verify,
)

register_webhook_source(
    WebhookSourceSpec(source=SOURCE, slug=SLUG, parser=parse, verifier=verify)
)
register_event_handler(SOURCE, to_document)
