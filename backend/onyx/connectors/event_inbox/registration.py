"""The one call that declares an event-based source.

This is the extension point. A source lives in one module and makes one
call; everything it claims -- its webhook endpoints, the handler that turns
a stored event into a document, and optionally the search behaviour that
withholds it from ordinary results -- is decided here.

A source does not have to live in this repository. `EVENT_SOURCE_MODULES`
takes module paths from configuration, so a package installed alongside
Onyx registers itself the same way a built-in one does. Keep this module's
signature stable: it is what such a package imports.
"""

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox.handlers import (
    EventHandler,
    event_handler_sources,
    register_event_handler,
    unregister_event_handler,
)
from onyx.connectors.event_inbox.models import WebhookSourceSpec
from onyx.connectors.event_inbox.source_registry import (
    register_webhook_source,
    registered_webhook_sources,
    unregister_webhook_source,
    webhook_source_for,
)
from onyx.context.search.enrichment.registry import (
    ChunkPermissionFilter,
    register_enrichment_source,
    registered_enrichment_sources,
    unregister_enrichment_source,
)


def register_event_source(
    webhook: WebhookSourceSpec,
    handler: EventHandler,
    permission_filter: ChunkPermissionFilter | None = None,
) -> None:
    """Declare one event-based source. Import-time.

    `webhook` says where deliveries arrive and how to prove and read them.
    `handler` turns a stored event into the document to index.

    Supply `permission_filter` only when the provider, not Onyx, decides who
    may read each document. The source is then withheld from ordinary search
    and served by a lane that clears every chunk with the provider
    ([[withheld-sources]]); without it, documents are searchable like any
    other connector's.

    The webhook spec is registered last. The route is the part the internet
    can reach, so it must not exist before the handler that drains it.
    """
    register_event_handler(webhook.source, handler)
    if permission_filter is not None:
        register_enrichment_source(webhook.source, permission_filter)
    register_webhook_source(webhook)


def unregister_event_source(source: DocumentSource) -> None:
    """Undo every registration one source holds. Unknown sources are
    ignored. Used by the loader to roll back a failed import, and by tests."""
    spec = webhook_source_for(source)
    if spec is not None:
        unregister_webhook_source(spec.slug)
    unregister_enrichment_source(source)
    unregister_event_handler(source)


def claimed_event_sources() -> set[DocumentSource]:
    """Every source holding a registration of any kind.

    Registrations only. The static withholding floor is not one, so a source
    listed there is not already "claimed" before its module runs; otherwise
    the loader's rollback would miss what a failed import left behind.
    """
    return (
        {spec.source for spec in registered_webhook_sources()}
        | registered_enrichment_sources()
        | event_handler_sources()
    )
