"""The event source modules, and the import that registers them.

A source registers when its module is imported, and nothing imports it by
accident. The webhook server and the drain call `load_event_sources`.
"""

import importlib

from onyx.connectors.event_inbox.source_registry import (
    register_webhook_source,
    registered_webhook_sources,
    unregister_webhook_source,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Paths, not modules, so reading the list does not import a source's SDK.
EVENT_SOURCE_MODULES: tuple[str, ...] = (
    # "onyx.connectors.zoom.events",
)

_loaded = False


def load_event_sources() -> None:
    """Import every event source module. Idempotent."""
    global _loaded
    if _loaded:
        return

    for module_path in EVENT_SOURCE_MODULES:
        before = registered_webhook_sources()
        try:
            importlib.import_module(module_path)
        except Exception:
            # Restore the registry, so one broken source neither stops the
            # others nor serves a half-registered spec.
            for spec in registered_webhook_sources():
                unregister_webhook_source(spec.slug)
            for spec in before:
                register_webhook_source(spec)
            logger.exception("Could not load event source %s", module_path)

    _loaded = True


def reset_event_sources() -> None:
    """Make the next `load_event_sources` import again. For tests, which
    unregister a source and then load it again."""
    global _loaded
    _loaded = False
