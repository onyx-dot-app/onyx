"""The one store of event sources, and the one call that declares one.

A source need not live in this repository: `EVENT_SOURCE_MODULES` takes
module paths from configuration, so an installed package registers the same
way a built-in one does. Keep these signatures stable.
"""

from pydantic import BaseModel, ConfigDict

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox.models import EventHandler, WebhookSourceSpec
from onyx.context.search.enrichment.models import ChunkPermissionFilter


class EventSource(BaseModel):
    """Everything one event source declared."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    webhook: WebhookSourceSpec
    handler: EventHandler
    # Set only when the provider decides who may read each document; the
    # source is then withheld from ordinary search ([[withheld-sources]]).
    permission_filter: ChunkPermissionFilter | None = None


_EVENT_SOURCES: dict[DocumentSource, EventSource] = {}


def register_event_source(
    webhook: WebhookSourceSpec,
    handler: EventHandler,
    permission_filter: ChunkPermissionFilter | None = None,
) -> None:
    """Declare one event source at import time. Refuses a source or slug
    another module holds, and stores nothing then."""
    record = EventSource(
        webhook=webhook, handler=handler, permission_filter=permission_filter
    )
    existing = _EVENT_SOURCES.get(webhook.source)
    if existing is not None and existing != record:
        raise ValueError(
            f"{webhook.source.value} is already declared as an event source."
        )
    slug_owner = get_event_source_by_slug(webhook.slug)
    if slug_owner is not None and slug_owner.webhook.source != webhook.source:
        raise ValueError(
            f"Webhook slug {webhook.slug} is already registered to "
            f"{slug_owner.webhook.source.value}."
        )
    _EVENT_SOURCES[webhook.source] = record


def unregister_event_source(source: DocumentSource) -> None:
    """For the loader's rollback and for tests. Ignores an unknown source."""
    _EVENT_SOURCES.pop(source, None)


def get_event_source(source: DocumentSource) -> EventSource | None:
    return _EVENT_SOURCES.get(source)


def get_event_source_by_slug(slug: str) -> EventSource | None:
    for record in _EVENT_SOURCES.values():
        if record.webhook.slug == slug:
            return record
    return None


def registered_event_sources() -> list[EventSource]:
    return sorted(_EVENT_SOURCES.values(), key=lambda record: record.webhook.slug)


def claimed_event_sources() -> set[DocumentSource]:
    return set(_EVENT_SOURCES)
