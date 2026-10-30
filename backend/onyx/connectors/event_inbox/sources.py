"""The list of event-based sources, and the import that registers them.

A `WebhookSourceSpec` and an event handler only exist once the module that
declares them is imported, and nothing imports a source by accident: the
connector registry loads source modules lazily, and the webhook server never
loads them at all. So the modules are named here and imported on purpose.

Add a source by appending its module path. That module calls
`register_webhook_source` and `register_event_handler` at import time.
"""

import importlib

from onyx.connectors.event_inbox.source_registry import _SPECS
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Module paths, not objects: importing this list must not pull a source's SDK
# into every process that only wants to know which sources exist.
EVENT_SOURCE_MODULES: tuple[str, ...] = (
    # "onyx.connectors.zoom.events",
)

_loaded = False


def load_event_sources() -> None:
    """Import every event source so its spec and handler are registered.

    Called by the webhook server when it builds its routes, and by the drain
    before it reads the queue, because the two run in different processes and
    each needs the registrations. Safe to call repeatedly.
    """
    global _loaded
    if _loaded:
        return

    for module_path in EVENT_SOURCE_MODULES:
        # A module registers partway through and can then raise, so the
        # registry is restored rather than left holding a source whose
        # import did not finish.
        before = dict(_SPECS)
        try:
            importlib.import_module(module_path)
        except Exception:
            # One broken source must not take down the server for the
            # others. Its route then does not exist, which is better than
            # one serving a half-registered spec.
            _SPECS.clear()
            _SPECS.update(before)
            logger.exception("Could not load event source %s", module_path)

    _loaded = True
