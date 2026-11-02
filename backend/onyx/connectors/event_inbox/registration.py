"""The one call that declares an event-based source.

This is the extension point, and a source need not live in this repository:
`EVENT_SOURCE_MODULES` takes module paths from configuration, so a package
installed alongside Onyx registers the same way a built-in one does. Keep
these signatures stable -- they are what such a package imports.
"""

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox.handlers import (
    EventHandler,
    event_handler_sources,
    get_event_handler,
    register_event_handler,
    unregister_event_handler,
)
from onyx.connectors.event_inbox.models import WebhookSourceSpec
from onyx.connectors.event_inbox.source_registry import (
    get_webhook_source,
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

    Supply `permission_filter` only when the provider, not Onyx, decides who
    may read each document; the source is then withheld from ordinary search
    ([[withheld-sources]]).

    Conflicts are found before anything is written, and the route is
    registered last: it is the part the internet can reach, so it must not
    exist before the handler that drains it, and a module refused here must
    not have replaced the incumbent's handler on the way.
    """
    _refuse_a_claimed_source(webhook)

    register_event_handler(webhook.source, handler)
    if permission_filter is not None:
        register_enrichment_source(webhook.source, permission_filter)
    register_webhook_source(webhook)


def _refuse_a_claimed_source(webhook: WebhookSourceSpec) -> None:
    """Raise unless every registry this call writes to is free to take it."""
    existing_slug = get_webhook_source(webhook.slug)
    if existing_slug is not None and existing_slug is not webhook:
        raise ValueError(
            f"Webhook slug {webhook.slug} is already registered to "
            f"{existing_slug.source.value}."
        )

    claimed = webhook_source_for(webhook.source)
    if claimed is not None and claimed.slug != webhook.slug:
        raise ValueError(
            f"{webhook.source.value} already receives events at "
            f"{claimed.slug}; a source has one endpoint."
        )

    handler = get_event_handler(webhook.source)
    if handler is not None and claimed is None:
        # The drain registry takes the last registration, so this is what
        # stops a module refused above from having replaced the handler.
        raise ValueError(
            f"{webhook.source.value} already has an event handler. Two "
            "modules cannot declare the same source."
        )


def unregister_event_source(source: DocumentSource) -> None:
    """Undo every registration one source holds, for the loader's rollback
    and for tests."""
    spec = webhook_source_for(source)
    if spec is not None:
        unregister_webhook_source(spec.slug)
    unregister_enrichment_source(source)
    unregister_event_handler(source)


def claimed_event_sources() -> set[DocumentSource]:
    """Every source holding a registration. Not the static withholding
    floor, which would make a source look claimed before its module runs and
    hide what a failed import left behind."""
    return (
        {spec.source for spec in registered_webhook_sources()}
        | registered_enrichment_sources()
        | event_handler_sources()
    )
