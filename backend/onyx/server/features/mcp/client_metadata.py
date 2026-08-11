from fastapi import APIRouter, Response
from pydantic import AnyUrl

from onyx.configs.app_configs import WEB_DOMAIN
from onyx.configs.constants import ONYX_DEFAULT_APPLICATION_NAME, PUBLIC_API_TAGS
from onyx.server.features.mcp.models import MCPOAuthClientMetadataDocument

MCP_OAUTH_CALLBACK_PATH = "/mcp/oauth/callback"
MCP_OAUTH_CLIENT_METADATA_ROUTE = "/oauth/client-metadata"
MCP_OAUTH_CLIENT_METADATA_PUBLIC_PATH = "/api/mcp/oauth/client-metadata"
MCP_OAUTH_CLIENT_METADATA_CACHE_CONTROL = "public, max-age=3600"

AUTHORIZATION_CODE_GRANT = "authorization_code"
REFRESH_TOKEN_GRANT = "refresh_token"
CODE_RESPONSE_TYPE = "code"
PUBLIC_CLIENT_AUTH_METHOD = "none"

router = APIRouter()


def mcp_oauth_redirect_uri() -> str:
    return f"{WEB_DOMAIN.rstrip('/')}{MCP_OAUTH_CALLBACK_PATH}"


def mcp_oauth_client_metadata_url() -> str:
    return f"{WEB_DOMAIN.rstrip('/')}{MCP_OAUTH_CLIENT_METADATA_PUBLIC_PATH}"


def build_mcp_oauth_client_metadata() -> MCPOAuthClientMetadataDocument:
    return MCPOAuthClientMetadataDocument(
        client_id=AnyUrl(mcp_oauth_client_metadata_url()),
        client_name=ONYX_DEFAULT_APPLICATION_NAME,
        redirect_uris=[AnyUrl(mcp_oauth_redirect_uri())],
        grant_types=[AUTHORIZATION_CODE_GRANT, REFRESH_TOKEN_GRANT],
        response_types=[CODE_RESPONSE_TYPE],
        token_endpoint_auth_method=PUBLIC_CLIENT_AUTH_METHOD,
    )


@router.get(MCP_OAUTH_CLIENT_METADATA_ROUTE, tags=PUBLIC_API_TAGS)
def get_mcp_oauth_client_metadata(
    response: Response,
) -> MCPOAuthClientMetadataDocument:
    response.headers["Cache-Control"] = MCP_OAUTH_CLIENT_METADATA_CACHE_CONTROL
    return build_mcp_oauth_client_metadata()
