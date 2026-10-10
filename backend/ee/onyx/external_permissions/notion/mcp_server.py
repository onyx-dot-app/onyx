"""Which registered MCP server the Notion censor may fetch pages through.
Kept apart from the censor so validation code can import it without the MCP
client stack."""

from urllib.parse import urlparse

from onyx.db.enums import MCPAuthenticationPerformer, MCPAuthenticationType
from onyx.db.models import MCPServer

NOTION_MCP_HOST = "mcp.notion.com"


def is_per_user_notion_mcp_server(mcp_server: MCPServer) -> bool:
    """A Notion MCP server whose grant belongs to each user. An admin-level
    server would act as the admin, so it never qualifies."""
    return (
        urlparse(mcp_server.server_url).hostname == NOTION_MCP_HOST
        and mcp_server.auth_type == MCPAuthenticationType.OAUTH
        and mcp_server.auth_performer == MCPAuthenticationPerformer.PER_USER
    )
