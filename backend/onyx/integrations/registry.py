from onyx.db.enums import IntegrationKind
from onyx.integrations.kinds.api import ApiKindHandler
from onyx.integrations.kinds.base import IntegrationKindHandler
from onyx.integrations.kinds.mcp_server import McpServerKindHandler


def _build_handlers() -> dict[IntegrationKind, IntegrationKindHandler]:
    handlers: dict[IntegrationKind, IntegrationKindHandler] = {}
    for handler in (McpServerKindHandler(), ApiKindHandler()):
        if handler.kind in handlers:
            raise RuntimeError(f"Two handlers for integration kind {handler.kind}.")
        handlers[handler.kind] = handler
    missing = set(IntegrationKind) - handlers.keys()
    if missing:
        raise RuntimeError(f"No handler for integration kinds {sorted(missing)}.")
    return handlers


_HANDLERS: dict[IntegrationKind, IntegrationKindHandler] = _build_handlers()


def get_kind_handler(kind: IntegrationKind) -> IntegrationKindHandler:
    return _HANDLERS[kind]
