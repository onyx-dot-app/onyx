from enum import Enum
from typing import Annotated, Any, Literal, NotRequired, TypedDict
from uuid import UUID

from pydantic import AnyUrl, BaseModel, ConfigDict, Field

from onyx.db.enums import (
    MCPAuthenticationType,
    MCPOAuthProviderMode,
    MCPServerStatus,
    MCPTransport,
)
from onyx.oauth.models import (
    PKCECodeVerifier,
)

# Headers that must never be sourced from stored MCP credentials or request
# templates. Host is particularly critical — it can be used for Host Header
# Injection attacks to route requests to unintended internal servers.
DENYLISTED_MCP_HEADERS = {
    "host",
}


def merge_mcp_headers(*sources: dict[str, str]) -> dict[str, str]:
    """Merge HTTP headers case-insensitively; later sources win."""
    merged: dict[str, str] = {}
    names_by_lower: dict[str, str] = {}
    for source in sources:
        for name, value in source.items():
            lowered = name.lower()
            if previous_name := names_by_lower.get(lowered):
                merged.pop(previous_name, None)
            merged[name] = value
            names_by_lower[lowered] = name
    return merged


# This should be updated along with MCPConnectionData
class MCPOAuthKeys(str, Enum):
    """MCP OAuth keys types"""

    CLIENT_INFO = "client_info"
    TOKENS = "tokens"
    METADATA = "metadata"
    # Absolute unix expiry for the stored token. `OAuthToken` only carries the
    # relative `expires_in`, which is meaningless once reloaded from storage.
    TOKEN_EXPIRES_AT = "token_expires_at"


class MCPConnectionStatus(str, Enum):
    NOT_CONNECTED = "not_connected"
    CONNECTED = "connected"
    REAUTH_REQUIRED = "reauth_required"


class MCPConnectionData(TypedDict):
    """TypedDict to allow use as a type hint for a JSONB column
    in Postgres"""

    headers: dict[str, str]
    # Admin-authored source template. User configs store its rendered result in
    # `headers`; admin-managed configs may render it at request time.
    header_template: NotRequired[dict[str, str]]
    # Stored in the encrypted connection config so an admin can edit the
    # header template without re-entering the masked API token.
    api_token: NotRequired[str]
    header_substitutions: NotRequired[dict[str, str]]
    # Names of fields the user must supply for header substitution. Persisted
    # only on the per-user template config (the admin's connection config that
    # serves as the template); empty/absent on regular per-user configs and on
    # admin-credential configs.
    required_fields: NotRequired[list[str]]

    # Confirmed credential rejection persists until credentials are replaced.
    reauth_required: NotRequired[bool]

    # For OAuth only
    # Note: Update MCPOAuthKeys if necessary when modifying these
    # Unfortunately we can't use the actual models here because basemodels aren't compatible
    # with SQLAlchemy
    oauth_setup_mode: NotRequired[Literal["automatic", "own_client"]]
    client_info: NotRequired[dict[str, Any]]  # OAuthClientInformationFull
    tokens: NotRequired[dict[str, Any]]  # OAuthToken
    metadata: NotRequired[dict[str, Any]]  # OAuthClientMetadata
    token_expires_at: NotRequired[float]  # absolute unix expiry for `tokens`

    # the actual models are defined in mcp.shared.auth
    # from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken


class MCPOAuthDiscoveryRequest(BaseModel):
    server_id: int


class MCPOAuthDiscoveryResponse(BaseModel):
    status: Literal["metadata_found", "metadata_missing", "unreachable"]
    supports_automatic_registration: bool | None = None
    supports_client_metadata: bool | None = None
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None


class MCPSetupProbeRequest(BaseModel):
    server_url: str


class MCPPublicProbeResult(BaseModel):
    kind: Literal["public"] = "public"
    transport: Literal[MCPTransport.STREAMABLE_HTTP, MCPTransport.SSE]
    tool_count: int
    server_name: str


class MCPOAuthProbeResult(BaseModel):
    kind: Literal["oauth"] = "oauth"
    transport: Literal[MCPTransport.STREAMABLE_HTTP, MCPTransport.SSE] | None = None
    discovery: MCPOAuthDiscoveryResponse


class MCPUnknownAuthProbeResult(BaseModel):
    kind: Literal["auth_unknown"] = "auth_unknown"
    transport: Literal[MCPTransport.STREAMABLE_HTTP, MCPTransport.SSE] | None = None


class MCPUnreachableProbeResult(BaseModel):
    kind: Literal["unreachable"] = "unreachable"
    reason: Literal["blocked", "connection_failed"] = "connection_failed"


MCPSetupProbeResult = Annotated[
    MCPPublicProbeResult
    | MCPOAuthProbeResult
    | MCPUnknownAuthProbeResult
    | MCPUnreachableProbeResult,
    Field(discriminator="kind"),
]


class MCPPendingOAuthAuthorization(BaseModel):
    authorization_url: str
    state: str
    code_verifier: PKCECodeVerifier


class MCPServerConnection(BaseModel):
    """Server settings needed for tool calls and token refresh."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    name: str
    server_url: str
    auth_type: MCPAuthenticationType | None
    transport: MCPTransport | None
    oauth_provider_mode: MCPOAuthProviderMode
    oauth_cimd_enabled: bool
    oauth_authorization_endpoint: str | None
    oauth_token_endpoint: str | None


class MCPOAuthClientMetadataDocument(BaseModel):
    client_id: AnyUrl
    client_name: str
    redirect_uris: list[AnyUrl]
    grant_types: list[Literal["authorization_code", "refresh_token"]]
    response_types: list[Literal["code"]]
    token_endpoint_auth_method: Literal["none"]


class MCPServer(BaseModel):
    """An MCP server of a plugin the user runs in Craft."""

    id: int
    name: str
    description: str | None
    server_url: str
    owner: str
    transport: MCPTransport | None
    connection_status: MCPConnectionStatus
    status: MCPServerStatus
    available_in_craft: bool
    # The plugins that hold the server's integration.
    plugin_ids: list[UUID]
    # Whether Craft can authenticate this user against the server.
    craft_connected: bool


class MCPServersResponse(BaseModel):
    mcp_servers: list[MCPServer]
