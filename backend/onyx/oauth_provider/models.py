from uuid import UUID

from mcp.server.auth.provider import AuthorizationCode, AuthorizationParams
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from onyx.auth.oauth_provider import OAuthProviderTokenKind


class OAuthProviderGrantInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    user_id: UUID
    client_id: str
    client_name: str
    resource: str
    scopes: tuple[str, ...]
    created_at: AwareDatetime
    expires_at: AwareDatetime
    revoked_at: AwareDatetime | None


class OAuthProviderTokenInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    grant: OAuthProviderGrantInfo
    kind: OAuthProviderTokenKind
    expires_at: AwareDatetime


class OAuthProviderTokenPair(BaseModel):
    model_config = ConfigDict(frozen=True)

    grant_id: UUID
    access_token: str = Field(repr=False)
    refresh_token: str | None = Field(default=None, repr=False)
    expires_at: AwareDatetime
    scopes: tuple[str, ...]


class PendingOAuthProviderAuthorization(BaseModel):
    model_config = ConfigDict(frozen=True)

    client_id: str
    client_name: str
    params: AuthorizationParams


class OAuthProviderConsentBinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: UUID
    tenant_id: str
    session_hash: str
    csrf_token: str = Field(repr=False)


class StoredOAuthProviderCode(BaseModel):
    model_config = ConfigDict(frozen=True)

    authorization: PendingOAuthProviderAuthorization
    user_id: UUID
    tenant_id: str
    expires_at: float
