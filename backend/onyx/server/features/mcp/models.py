from enum import Enum
from typing import Any
from typing import List
from typing import NotRequired
from typing import Optional
from typing import TypedDict

from mcp.types import Tool as MCPLibTool
from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator

from onyx.db.enums import MCPAuthenticationPerformer
from onyx.db.enums import MCPAuthenticationType
from onyx.db.enums import MCPTransport


# This should be updated along with MCPConnectionData
class MCPOAuthKeys(str, Enum):
    """MCP OAuth keys types"""

    CLIENT_INFO = "client_info"
    TOKENS = "tokens"
    METADATA = "metadata"


class MCPConnectionData(TypedDict):
    """TypedDict to allow use as a type hint for a JSONB column
    in Postgres"""

    headers: dict[str, str]
    header_substitutions: NotRequired[dict[str, str]]

    # For OAuth only
    # Note: Update MCPOAuthKeys if necessary when modifying these
    # Unfortunately we can't use the actual models here because basemodels aren't compatible
    # with SQLAlchemy
    client_info: NotRequired[dict[str, Any]]  # OAuthClientInformationFull
    tokens: NotRequired[dict[str, Any]]  # OAuthToken
    metadata: NotRequired[dict[str, Any]]  # OAuthClientMetadata

    # the actual models are defined in mcp.shared.auth
    # from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken


class MCPAuthTemplate(BaseModel):
    """Template for per-user authentication configuration"""

    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Map of header names to templates with placeholders",
    )
    # request_body_params: List[dict[str, str]] = Field(
    #     default_factory=list,
    #     description="List of request body parameter templates with path/value pairs",
    # ) # not used yet
    required_fields: List[str] = Field(
        default_factory=list,
        description="List of required field names that users must provide",
    )


class MCPToolCreateRequest(BaseModel):
    name: str = Field(..., description="Name of the MCP tool")
    description: Optional[str] = Field(None, description="Description of the MCP tool")
    server_url: str = Field(..., description="URL of the MCP server")
    auth_type: MCPAuthenticationType = Field(..., description="Authentication type")
    auth_performer: MCPAuthenticationPerformer = Field(
        ..., description="Who performs authentication"
    )
    api_token: Optional[str] = Field(
        None, description="API token for api_token auth type"
    )
    oauth_client_id: Optional[str] = Field(None, description="OAuth client ID")
    oauth_client_secret: Optional[str] = Field(None, description="OAuth client secret")
    transport: MCPTransport | None = Field(
        None, description="MCP transport type (STREAMABLE_HTTP or SSE)"
    )
    auth_template: Optional[MCPAuthTemplate] = Field(
        None, description="Template configuration for per-user authentication"
    )
    admin_credentials: Optional[dict[str, str]] = Field(
        None,
        description="Admin's credential key-value pairs for template substitution and storage",
    )
    existing_server_id: Optional[int] = Field(
        None, description="ID of existing server to update (for editing)"
    )

    @model_validator(mode="after")
    def validate_auth_configuration(self) -> "MCPToolCreateRequest":
        # Validate API token requirements for admin auth
        if (
            self.auth_type == MCPAuthenticationType.API_TOKEN
            and self.auth_performer == MCPAuthenticationPerformer.ADMIN
            and not self.api_token
        ):
            raise ValueError(
                "api_token is required when auth_type is 'api_token' and auth_performer is 'admin'"
            )

        # Validate that API token is not provided for per-user auth
        if (
            self.auth_type == MCPAuthenticationType.API_TOKEN
            and self.auth_performer == MCPAuthenticationPerformer.PER_USER
            and self.api_token
            and self.api_token.strip()
        ):
            raise ValueError(
                "api_token should not be provided when auth_performer is 'per_user'. Users will provide their own credentials."
            )

        # Validate that auth_template is provided for per-user auth
        if (
            self.auth_type == MCPAuthenticationType.API_TOKEN
            and self.auth_performer == MCPAuthenticationPerformer.PER_USER
        ):
            if not self.auth_template:
                raise ValueError(
                    "auth_template is required when auth_performer is 'per_user'"
                )
            if not self.admin_credentials:
                raise ValueError(
                    "admin_credentials is required when auth_performer is 'per_user'"
                )

        # OAuth client ID/secret are optional. If provided, they will seed the
        # OAuth client info; otherwise, the MCP client will attempt dynamic
        # client registration.

        return self


class MCPToolUpdateRequest(BaseModel):
    server_id: int = Field(..., description="ID of the MCP server")
    selected_tools: Optional[List[str]] = Field(
        None, description="List of selected tool names to create"
    )


class MCPToolResponse(BaseModel):
    id: int
    name: str
    display_name: str
    description: str
    definition: Optional[dict] = None  # MCP tools don't use OpenAPI definitions
    custom_headers: List[dict] = []
    in_code_tool_id: Optional[str] = None
    passthrough_auth: bool = False
    # MCP-specific fields
    server_url: str
    auth_type: str
    auth_performer: Optional[str] = None
    is_authenticated: bool


class MCPOAuthConnectRequest(BaseModel):
    name: str = Field(..., description="Name of the MCP tool")
    description: Optional[str] = Field(None, description="Description of the MCP tool")
    server_url: str = Field(..., description="URL of the MCP server")
    selected_tools: Optional[List[str]] = Field(
        None, description="List of selected tool names to create"
    )
    existing_server_id: Optional[int] = Field(
        None, description="ID of existing server to update (for editing)"
    )


class MCPOAuthConnectResponse(BaseModel):
    oauth_url: str = Field(..., description="OAuth URL to redirect user to")
    state: str = Field(..., description="OAuth state parameter")
    pending_tool: dict = Field(..., description="Pending tool configuration")


class MCPUserOAuthConnectRequest(BaseModel):
    server_id: int = Field(..., description="ID of the MCP server")
    return_path: str = Field(..., description="Path to redirect to after callback")
    include_resource_param: bool = Field(..., description="Include resource parameter")
    oauth_client_id: str | None = Field(
        None, description="OAuth client ID (optional for DCR)"
    )
    oauth_client_secret: str | None = Field(
        None, description="OAuth client secret (optional for DCR)"
    )

    @model_validator(mode="after")
    def validate_return_path(self) -> "MCPUserOAuthConnectRequest":
        if not self.return_path.startswith("/"):
            raise ValueError("return_path must start with a slash")
        return self


class MCPUserOAuthConnectResponse(BaseModel):
    server_id: int
    oauth_url: str = Field(..., description="OAuth URL to redirect user to")


class MCPOAuthCallbackRequest(BaseModel):
    """Request payload for completing OAuth flow (authorization code exchange)."""

    code: str = Field(..., description="Authorization code returned by the IdP")
    state: Optional[str] = Field(
        None, description="State parameter for CSRF protection"
    )


class MCPOAuthCallbackResponse(BaseModel):
    success: bool
    message: str
    server_id: int
    server_name: str
    redirect_url: str


class MCPDynamicClientRegistrationRequest(BaseModel):
    """Request for dynamic client registration per RFC 7591"""

    server_id: int = Field(..., description="MCP server ID")
    authorization_server_url: str = Field(
        ...,
        description="Authorization server URL discovered from WWW-Authenticate or metadata",
    )


class MCPDynamicClientRegistrationResponse(BaseModel):
    """Response from dynamic client registration"""

    client_id: str = Field(..., description="Registered client ID")
    client_secret: Optional[str] = Field(
        None, description="Client secret if confidential client"
    )
    registration_access_token: Optional[str] = Field(
        None, description="Token for managing this client registration"
    )
    registration_client_uri: Optional[str] = Field(
        None, description="URI for managing this client registration"
    )


class MCPApiKeyRequest(BaseModel):
    server_id: int = Field(..., description="ID of the MCP server")
    api_key: str = Field(..., description="API key to store")
    transport: str = Field(..., description="Transport type")


class MCPUserCredentialsRequest(BaseModel):
    """Enhanced request for template-based user credentials"""

    server_id: int = Field(..., description="ID of the MCP server")
    credentials: dict[str, str] = Field(
        ..., description="User-provided credentials (api_key, custom_token, etc.)"
    )
    transport: str = Field(..., description="Transport type")


class MCPApiKeyResponse(BaseModel):
    success: bool
    message: str
    server_id: int
    server_name: str
    authenticated: bool
    validation_tested: bool = Field(
        default=False, description="Whether credentials were tested against MCP server"
    )


class MCPServer(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    server_url: str
    owner: str
    transport: MCPTransport
    auth_type: MCPAuthenticationType
    auth_performer: MCPAuthenticationPerformer
    is_authenticated: bool
    user_authenticated: Optional[bool] = None
    auth_template: Optional[MCPAuthTemplate] = Field(
        None, description="Authentication template for per-user auth"
    )
    user_credentials: Optional[dict[str, str]] = Field(
        None, description="User's existing credentials for pre-filling forms"
    )
    admin_credentials: Optional[dict[str, str]] = Field(
        None,
        description="Admin's credential key-value pairs for template substitution and storage",
    )


class MCPServersResponse(BaseModel):
    assistant_id: str | None = None
    mcp_servers: List[MCPServer]


class MCPServerCreateResponse(BaseModel):
    """Response for creating multiple MCP tools"""

    server_id: int
    server_name: str
    server_url: str
    auth_type: str
    auth_performer: Optional[str]
    is_authenticated: bool


class MCPServerUpdateResponse(BaseModel):
    """Response for updating multiple MCP tools"""

    server_id: int
    updated_tools: int


class MCPToolListResponse(BaseModel):
    server_id: int
    server_name: str
    server_url: str
    tools: list[MCPLibTool]
