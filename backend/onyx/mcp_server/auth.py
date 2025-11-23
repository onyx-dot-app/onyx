"""Authentication helpers for the Onyx MCP server."""

from typing import Optional

from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.auth import TokenVerifier

from onyx.mcp_server.utils import get_api_server_url
from onyx.mcp_server.utils import get_http_client
from onyx.utils.logger import setup_logger

logger = setup_logger()


class OnyxTokenVerifier(TokenVerifier):
    """Validates bearer tokens by delegating to the API server."""

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        """Call API /me to verify the token, return minimal AccessToken on success."""
        try:
            response = await get_http_client().get(
                f"{get_api_server_url()}/me",
                headers={"Authorization": f"Bearer {token}"},
            )
        except Exception as exc:
            logger.error(
                "MCP server failed to reach API /me for authentication: %s",
                exc,
                exc_info=True,
            )
            return None

        if response.status_code != 200:
            logger.warning(
                "API server rejected MCP auth token with status %s",
                response.status_code,
            )
            return None

        return AccessToken(
            token=token,
            client_id="mcp",
            scopes=["mcp:use"],
            expires_at=None,
            resource=None,
            claims={},
        )
