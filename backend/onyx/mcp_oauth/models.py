from uuid import UUID

from mcp.server.auth.provider import AuthorizationParams
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from onyx.auth.mcp_oauth import MCPOAuthTokenKind


class MCPOAuthGrantInfo(BaseModel):
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


class MCPOAuthTokenInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    grant: MCPOAuthGrantInfo
    kind: MCPOAuthTokenKind
    expires_at: AwareDatetime


class MCPOAuthTokenPair(BaseModel):
    model_config = ConfigDict(frozen=True)

    grant_id: UUID
    access_token: str = Field(repr=False)
    refresh_token: str | None = Field(default=None, repr=False)
    expires_at: AwareDatetime
    scopes: tuple[str, ...]


class PendingMCPOAuthAuthorization(BaseModel):
    model_config = ConfigDict(frozen=True)

    client_id: str
    client_name: str
    params: AuthorizationParams


class MCPOAuthConsentBinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: UUID
    tenant_id: str
    session_hash: str
    csrf_token: str = Field(repr=False)


class StoredMCPOAuthCode(BaseModel):
    model_config = ConfigDict(frozen=True)

    authorization: PendingMCPOAuthAuthorization
    user_id: UUID
    tenant_id: str
    expires_at: float
