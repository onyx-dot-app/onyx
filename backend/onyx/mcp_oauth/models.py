from uuid import UUID

from mcp.server.auth.provider import AuthorizationCode
from pydantic import BaseModel, ConfigDict


class MCPOAuthAuthorizationCode(AuthorizationCode):
    tenant_id: str
    user_id: UUID


class MCPOAuthOwner(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: UUID
    email: str
    oauth_identities: tuple[tuple[str, str], ...]
