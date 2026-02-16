"""Pydantic schemas for SCIM 2.0 provisioning (RFC 7643 / RFC 7644).

SCIM protocol schemas follow the wire format defined in:
  - Core Schema: https://datatracker.ietf.org/doc/html/rfc7643
  - Protocol:    https://datatracker.ietf.org/doc/html/rfc7644

Admin API schemas are internal to Onyx and used for SCIM token management.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


# ---------------------------------------------------------------------------
# SCIM Schema URIs (RFC 7643 §8)
# Every SCIM JSON payload includes a "schemas" array identifying its type.
# IdPs like Okta/Azure AD use these URIs to determine how to parse responses.
# ---------------------------------------------------------------------------

SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCIM_LIST_RESPONSE_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_PATCH_OP_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
SCIM_ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
SCIM_SERVICE_PROVIDER_CONFIG_SCHEMA = (
    "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"
)
SCIM_RESOURCE_TYPE_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:ResourceType"


# ---------------------------------------------------------------------------
# SCIM Protocol Schemas
# ---------------------------------------------------------------------------


class ScimName(BaseModel):
    """User name components (RFC 7643 §4.1.1)."""

    givenName: str | None = None
    familyName: str | None = None
    formatted: str | None = None


class ScimEmail(BaseModel):
    """Email sub-attribute (RFC 7643 §4.1.2)."""

    value: str
    type: str | None = None
    primary: bool = False


class ScimMeta(BaseModel):
    """Resource metadata (RFC 7643 §3.1)."""

    resourceType: str | None = None
    created: datetime | None = None
    lastModified: datetime | None = None
    location: str | None = None


class ScimUserResource(BaseModel):
    """SCIM User resource representation (RFC 7643 §4.1).

    This is the JSON shape that IdPs send when creating/updating a user via
    SCIM, and the shape we return in GET responses. Field names use camelCase
    to match the SCIM wire format (not Python convention).
    """

    schemas: list[str] = Field(default_factory=lambda: [SCIM_USER_SCHEMA])
    id: str | None = None  # Onyx's internal user ID, set on responses
    externalId: str | None = None  # IdP's identifier for this user
    userName: str  # Typically the user's email address
    name: ScimName | None = None
    emails: list[ScimEmail] = Field(default_factory=list)
    active: bool = True
    meta: ScimMeta | None = None


class ScimGroupMember(BaseModel):
    """Group member reference (RFC 7643 §4.2).

    Represents a user within a SCIM group. The IdP sends these when adding
    or removing users from groups. ``value`` is the Onyx user ID.
    """

    value: str  # User ID of the group member
    display: str | None = None


class ScimGroupResource(BaseModel):
    """SCIM Group resource representation (RFC 7643 §4.2)."""

    schemas: list[str] = Field(default_factory=lambda: [SCIM_GROUP_SCHEMA])
    id: str | None = None
    externalId: str | None = None
    displayName: str
    members: list[ScimGroupMember] = Field(default_factory=list)
    meta: ScimMeta | None = None


class ScimListResponse(BaseModel):
    """Paginated list response (RFC 7644 §3.4.2)."""

    schemas: list[str] = Field(default_factory=lambda: [SCIM_LIST_RESPONSE_SCHEMA])
    totalResults: int
    startIndex: int = 1
    itemsPerPage: int = 100
    Resources: list[ScimUserResource | ScimGroupResource] = Field(default_factory=list)


class ScimPatchOperationType(str, Enum):
    """Supported PATCH operations (RFC 7644 §3.5.2)."""

    ADD = "add"
    REPLACE = "replace"
    REMOVE = "remove"


class ScimPatchOperation(BaseModel):
    """Single PATCH operation (RFC 7644 §3.5.2)."""

    op: ScimPatchOperationType
    path: str | None = None
    value: str | list[dict[str, str]] | dict[str, str | bool] | bool | None = None


class ScimPatchRequest(BaseModel):
    """PATCH request body (RFC 7644 §3.5.2).

    IdPs use PATCH to make incremental changes — e.g. deactivating a user
    (replace active=false) or adding/removing group members — instead of
    replacing the entire resource with PUT.
    """

    schemas: list[str] = Field(default_factory=lambda: [SCIM_PATCH_OP_SCHEMA])
    Operations: list[ScimPatchOperation]


class ScimError(BaseModel):
    """SCIM error response (RFC 7644 §3.12)."""

    schemas: list[str] = Field(default_factory=lambda: [SCIM_ERROR_SCHEMA])
    status: str
    detail: str | None = None
    scimType: str | None = None


# ---------------------------------------------------------------------------
# Service Provider Configuration (RFC 7643 §5)
# ---------------------------------------------------------------------------


class ScimSupported(BaseModel):
    """Generic supported/not-supported flag used in ServiceProviderConfig."""

    supported: bool


class ScimFilterConfig(BaseModel):
    """Filter configuration within ServiceProviderConfig (RFC 7643 §5)."""

    supported: bool
    maxResults: int = 100


class ScimServiceProviderConfig(BaseModel):
    """SCIM ServiceProviderConfig resource (RFC 7643 §5).

    Served at GET /scim/v2/ServiceProviderConfig. IdPs fetch this during
    initial setup to discover which SCIM features our server supports
    (e.g. PATCH yes, bulk no, filtering yes).
    """

    schemas: list[str] = Field(
        default_factory=lambda: [SCIM_SERVICE_PROVIDER_CONFIG_SCHEMA]
    )
    patch: ScimSupported = ScimSupported(supported=True)
    bulk: ScimSupported = ScimSupported(supported=False)
    filter: ScimFilterConfig = ScimFilterConfig(supported=True)
    changePassword: ScimSupported = ScimSupported(supported=False)
    sort: ScimSupported = ScimSupported(supported=False)
    etag: ScimSupported = ScimSupported(supported=False)
    authenticationSchemes: list[dict[str, str]] = Field(
        default_factory=lambda: [
            {
                "type": "oauthbearertoken",
                "name": "OAuth Bearer Token",
                "description": "Authentication scheme using a SCIM bearer token",
            }
        ]
    )


class ScimSchemaExtension(BaseModel):
    """Schema extension reference within ResourceType (RFC 7643 §6)."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(alias="schema")
    required: bool


class ScimResourceType(BaseModel):
    """SCIM ResourceType resource (RFC 7643 §6).

    Served at GET /scim/v2/ResourceTypes. Tells the IdP which resource
    types are available (Users, Groups) and their respective endpoints.
    """

    model_config = ConfigDict(populate_by_name=True)

    schemas: list[str] = Field(default_factory=lambda: [SCIM_RESOURCE_TYPE_SCHEMA])
    id: str
    name: str
    endpoint: str
    description: str | None = None
    schema_: str = Field(alias="schema")
    schemaExtensions: list[ScimSchemaExtension] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Admin API Schemas (Onyx-internal, for SCIM token management)
# These are NOT part of the SCIM protocol. They power the Onyx admin UI
# where admins create/revoke the bearer tokens that IdPs use to authenticate.
# ---------------------------------------------------------------------------


class ScimTokenCreate(BaseModel):
    """Request to create a new SCIM bearer token."""

    name: str


class ScimTokenResponse(BaseModel):
    """SCIM token metadata returned in list/get responses."""

    id: int
    name: str
    token_display: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None = None


class ScimTokenCreatedResponse(ScimTokenResponse):
    """Response returned when a new SCIM token is created.

    Includes the raw token value which is only available at creation time.
    """

    raw_token: str
