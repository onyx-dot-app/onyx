"""A mock event source that registers at import, the way a real one does
when the loader names it in `EVENT_SOURCE_MODULES`."""

from onyx.connectors.event_inbox.models import WebhookSourceSpec
from onyx.connectors.event_inbox.registration import register_event_source
from tests.external_dependency_unit.connectors.mock_event_source_protocol import (
    SLUG,
    SOURCE,
    parse,
    to_document,
    verify,
)

# No permission filter: its documents are searchable like any connector's.
register_event_source(
    webhook=WebhookSourceSpec(source=SOURCE, slug=SLUG, parser=parse, verifier=verify),
    handler=to_document,
)
