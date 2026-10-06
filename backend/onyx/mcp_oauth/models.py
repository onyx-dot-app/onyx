from uuid import UUID

from mcp.server.auth.provider import AuthorizationCode
from pydantic import BaseModel, ConfigDict

from onyx.oauth_provider import models as _oauth_provider_models

MCPOAuthConsentBinding = _oauth_provider_models.OAuthProviderConsentBinding
MCPOAuthGrantInfo = _oauth_provider_models.OAuthProviderGrantInfo
MCPOAuthTokenInfo = _oauth_provider_models.OAuthProviderTokenInfo
MCPOAuthTokenPair = _oauth_provider_models.OAuthProviderTokenPair
PendingMCPOAuthAuthorization = _oauth_provider_models.PendingOAuthProviderAuthorization
StoredMCPOAuthCode = _oauth_provider_models.StoredOAuthProviderCode


class MCPOAuthAuthorizationCode(AuthorizationCode):
    tenant_id: str
    user_id: UUID


class MCPOAuthOwner(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: UUID
    email: str
    oauth_identities: tuple[tuple[str, str], ...]
