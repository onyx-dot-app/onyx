"""Register an event source for a test, with stub parts for what the test
does not exercise, and restore whatever held the source afterwards."""

from collections.abc import Generator, Mapping
from contextlib import contextmanager

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox.models import (
    EventHandler,
    WebhookRequest,
    WebhookSourceSpec,
)
from onyx.connectors.event_inbox.registration import (
    get_event_source,
    register_event_source,
    unregister_event_source,
)
from onyx.connectors.event_models import EventParseResult
from onyx.connectors.models import Document
from onyx.context.search.enrichment.models import ChunkPermissionFilter
from onyx.db.models import ConnectorEventInbox


def stub_parse(request: WebhookRequest) -> EventParseResult:  # noqa: ARG001
    return EventParseResult()


def stub_handler(
    event: ConnectorEventInbox,  # noqa: ARG001
    secrets: Mapping[str, str],  # noqa: ARG001
) -> Document | None:
    return None


def stub_webhook(source: DocumentSource, slug: str | None = None) -> WebhookSourceSpec:
    return WebhookSourceSpec(
        source=source,
        slug=slug or f"test-{source.value}",
        parser=stub_parse,
        verifier=None,
        allow_unsigned=True,
    )


def declare_event_source(
    source: DocumentSource,
    *,
    webhook: WebhookSourceSpec | None = None,
    handler: EventHandler | None = None,
    permission_filter: ChunkPermissionFilter | None = None,
) -> None:
    """Replace the source's registration, filling unset parts with stubs."""
    unregister_event_source(source)
    register_event_source(
        webhook=webhook or stub_webhook(source),
        handler=handler or stub_handler,
        permission_filter=permission_filter,
    )


@contextmanager
def event_source_registered(
    source: DocumentSource,
    *,
    webhook: WebhookSourceSpec | None = None,
    handler: EventHandler | None = None,
    permission_filter: ChunkPermissionFilter | None = None,
) -> Generator[None, None, None]:
    displaced = get_event_source(source)
    declare_event_source(
        source, webhook=webhook, handler=handler, permission_filter=permission_filter
    )
    try:
        yield
    finally:
        unregister_event_source(source)
        if displaced is not None:
            register_event_source(
                webhook=displaced.webhook,
                handler=displaced.handler,
                permission_filter=displaced.permission_filter,
            )
