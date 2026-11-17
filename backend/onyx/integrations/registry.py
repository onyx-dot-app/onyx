from onyx.db.enums import IntegrationKind
from onyx.integrations.kinds.api import ApiKindHandler
from onyx.integrations.kinds.base import IntegrationKindHandler
from onyx.integrations.kinds.mcp_server import McpServerKindHandler

_HANDLERS: dict[IntegrationKind, IntegrationKindHandler] = {
    IntegrationKind.MCP: McpServerKindHandler(),
    IntegrationKind.API: ApiKindHandler(),
}


def get_kind_handler(kind: IntegrationKind) -> IntegrationKindHandler:
    return _HANDLERS[kind]
