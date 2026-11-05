"""Sources that are indexed but kept out of the default search lane.

For these the provider, not Onyx, decides who may read each document, and
the answer can change after indexing. A lane of its own retrieves them and
asks the provider about every chunk first. A source becomes one by passing a
`permission_filter` to `register_event_source`.
"""

from onyx.configs.constants import WITHHELD_FROM_DEFAULT_SEARCH, DocumentSource
from onyx.connectors.event_inbox.registration import (
    get_event_source,
    registered_event_sources,
)
from onyx.context.search.enrichment.models import ChunkPermissionFilter


def get_enrichment_filter(source: DocumentSource) -> ChunkPermissionFilter | None:
    record = get_event_source(source)
    return record.permission_filter if record is not None else None


def enrichment_source_types() -> list[DocumentSource]:
    """What the default lane must not return. The floor is unioned in, so a
    source stays withheld even when its module is absent."""
    registered = {
        record.webhook.source
        for record in registered_event_sources()
        if record.permission_filter is not None
    }
    return sorted(
        registered | WITHHELD_FROM_DEFAULT_SEARCH, key=lambda source: source.value
    )
