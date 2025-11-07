"""PAT authentication for MCP server using FastMCP's native auth system."""

from typing import Optional
from urllib.parse import unquote

from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.auth import TokenVerifier

from onyx.auth.constants import PAT_PREFIX
from onyx.auth.pat import hash_pat
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.pat import fetch_user_for_pat
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


def _extract_tenant_from_pat(token: str) -> str | None:
    """Extract tenant ID from PAT token string.

    PAT format: <prefix><tenant>.<random_string>
    e.g., onyx_pat_tenant123.randomsecret

    Args:
        token: The raw PAT token string

    Returns:
        Tenant ID if found and valid format, else None
    """
    if not token.startswith(PAT_PREFIX):
        return None

    # Remove prefix and parse: <tenant>.<random>
    parts = token[len(PAT_PREFIX) :].split(".", 1)
    if len(parts) != 2:
        return None

    tenant_id = parts[0]
    return unquote(tenant_id) if tenant_id else None


class OnyxPATVerifier(TokenVerifier):
    """Verifies Onyx Personal Access Tokens and returns user info."""

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        """
        Verify PAT and return AccessToken with user information in claims.

        Args:
            token: The PAT from Authorization: Bearer header

        Returns:
            AccessToken with user data in claims, or None if invalid
        """
        try:
            # Hash the PAT
            hashed_pat = hash_pat(token)

            # Look up user for this PAT
            async with get_async_session_context_manager() as db_session:
                user = await fetch_user_for_pat(hashed_pat, db_session)

            if user is None:
                logger.warning(f"Invalid PAT: {hashed_pat[:8]}...")
                return None

            # Extract tenant if multi-tenant mode
            tenant_id = None
            if MULTI_TENANT:
                # Extract tenant from token string (PATs encode tenant in format)
                tenant_id = _extract_tenant_from_pat(token)
                if not tenant_id:
                    logger.error("Multi-tenant enabled but no tenant in PAT")
                    return None

            logger.debug(f"Authenticated: {user.email}, tenant: {tenant_id}")

            # Return AccessToken with user data in claims
            # FastMCP will make this available to tools via get_access_token()
            return AccessToken(
                token=token,
                client_id=user.email,
                scopes=["mcp:use"],
                expires_at=None,  # PAT expiration handled by fetch_user_for_pat
                resource=None,
                claims={
                    "user_id": user.id,
                    "email": user.email,
                    "role": user.role.value,
                    "tenant_id": tenant_id,
                    # Store the entire user object for tools to access
                    # Note: This is safe because AccessToken is request-scoped
                    "_user": user,  # Internal: full User object
                },
            )

        except Exception as e:
            logger.error(f"PAT verification error: {e}", exc_info=True)
            return None
