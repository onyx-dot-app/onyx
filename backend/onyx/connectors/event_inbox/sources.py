"""The event source modules, and the import that registers them.

A source registers when its module is imported, and nothing imports it by
accident. The webhook server, the drain and search call `load_event_sources`.
"""

import importlib

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox.handlers import (
    event_handler_sources,
    unregister_event_handler,
)
from onyx.connectors.event_inbox.source_registry import (
    registered_webhook_sources,
    unregister_webhook_source,
    webhook_source_for,
)
from onyx.context.search.enrichment.registry import (
    enrichment_source_types,
    unregister_enrichment_source,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Paths, not modules, so reading the list does not import a source's SDK.
EVENT_SOURCE_MODULES: tuple[str, ...] = ()

_loaded = False


def _claimed_sources() -> set[DocumentSource]:
    """Every source that holds a registration of any kind."""
    return (
        {spec.source for spec in registered_webhook_sources()}
        | set(enrichment_source_types())
        | event_handler_sources()
    )


def _give_up(source: DocumentSource) -> None:
    """Undo every registration one source holds."""
    spec = webhook_source_for(source)
    if spec is not None:
        unregister_webhook_source(spec.slug)
    unregister_enrichment_source(source)
    unregister_event_handler(source)


def load_event_sources() -> None:
    """Import every event source module. Idempotent."""
    global _loaded
    if _loaded:
        return

    for module_path in EVENT_SOURCE_MODULES:
        before = _claimed_sources()
        try:
            importlib.import_module(module_path)
        except Exception:
            # Drop only what this module added, so one broken source neither
            # stops the others nor serves a half-registered spec.
            for source in _claimed_sources() - before:
                _give_up(source)
            logger.exception("Could not load event source %s", module_path)

    _loaded = True


def reset_event_sources() -> None:
    """Make the next `load_event_sources` import again. For tests, which
    unregister a source and then load it again."""
    global _loaded
    _loaded = False
