from uuid import UUID

from mcp.server.auth.provider import AuthorizationCode
from pydantic import BaseModel, ConfigDict

from onyx.oauth_provider.models import (
    OAuthProviderConsentBinding as MCPOAuthConsentBinding,
    OAuthProviderGrantInfo as MCPOAuthGrantInfo,
    PendingOAuthProviderAuthorization as PendingMCPOAuthAuthorization,
    StoredOAuthProviderCode as StoredMCPOAuthCode,
    OAuthProviderTokenInfo as MCPOAuthTokenInfo,
    OAuthProviderTokenPair as MCPOAuthTokenPair,
)


class MCPOAuthAuthorizationCode(AuthorizationCode):
    tenant_id: str
    user_id: UUID


class MCPOAuthOwner(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: UUID
    email: str
    oauth_identities: tuple[tuple[str, str], ...]


class MCPOAuthIntrospection(BaseModel):
    client_id: str
    scopes: list[str]
    resource: str
    expires_at: int
    subject: str
    grant_id: UUID

