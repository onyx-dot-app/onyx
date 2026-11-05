"""The event source modules, and the import that registers them.

A source registers when its module is imported, and nothing imports it by
accident. The webhook server, the drain and search call `load_event_sources`.
"""

import importlib

from onyx.configs.app_configs import EXTRA_EVENT_SOURCE_MODULES
from onyx.connectors.event_inbox.registration import (
    claimed_event_sources,
    unregister_event_source,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Paths, not modules, so reading the list does not import a source's SDK.
_BUILT_IN_EVENT_SOURCE_MODULES: tuple[str, ...] = ()
EVENT_SOURCE_MODULES: tuple[str, ...] = (
    _BUILT_IN_EVENT_SOURCE_MODULES + EXTRA_EVENT_SOURCE_MODULES
)

_loaded = False


def load_event_sources() -> None:
    """Import every event source module. Idempotent."""
    global _loaded
    if _loaded:
        return

    for module_path in EVENT_SOURCE_MODULES:
        before = claimed_event_sources()
        try:
            importlib.import_module(module_path)
        except Exception:
            # Drop only what this module added, so one broken source neither
            # stops the others nor serves a half-registered spec.
            for source in claimed_event_sources() - before:
                unregister_event_source(source)
            logger.exception("Could not load event source %s", module_path)

    _loaded = True


def reset_event_sources() -> None:
    """Make the next `load_event_sources` import again. For tests, which
    unregister a source and then load it again."""
    global _loaded
    _loaded = False
