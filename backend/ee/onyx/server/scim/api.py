"""SCIM 2.0 API endpoints (RFC 7644).

This module provides the FastAPI router for SCIM service discovery,
User CRUD, and Group CRUD. Identity providers (Okta, Azure AD) call
these endpoints to provision and manage users and groups.

Service discovery endpoints are unauthenticated — IdPs may probe them
before bearer token configuration is complete. All other endpoints
require a valid SCIM bearer token.
"""

from __future__ import annotations

from fastapi import APIRouter

from ee.onyx.server.scim.models import ScimResourceType
from ee.onyx.server.scim.models import ScimSchemaDefinition
from ee.onyx.server.scim.models import ScimServiceProviderConfig
from ee.onyx.server.scim.schema_definitions import GROUP_RESOURCE_TYPE
from ee.onyx.server.scim.schema_definitions import GROUP_SCHEMA_DEF
from ee.onyx.server.scim.schema_definitions import SERVICE_PROVIDER_CONFIG
from ee.onyx.server.scim.schema_definitions import USER_RESOURCE_TYPE
from ee.onyx.server.scim.schema_definitions import USER_SCHEMA_DEF


# NOTE: All URL paths in this router (/ServiceProviderConfig, /ResourceTypes,
# /Schemas, /Users, /Groups) are mandated by the SCIM spec (RFC 7643/7644).
# IdPs like Okta and Azure AD hardcode these exact paths, so they cannot be
# changed to kebab-case.
scim_router = APIRouter(prefix="/scim/v2", tags=["SCIM"])


# ---------------------------------------------------------------------------
# Service Discovery Endpoints (unauthenticated)
# ---------------------------------------------------------------------------


@scim_router.get("/ServiceProviderConfig")
def get_service_provider_config() -> ScimServiceProviderConfig:
    """Advertise supported SCIM features (RFC 7643 §5)."""
    return SERVICE_PROVIDER_CONFIG


@scim_router.get("/ResourceTypes")
def get_resource_types() -> list[ScimResourceType]:
    """List available SCIM resource types (RFC 7643 §6)."""
    return [USER_RESOURCE_TYPE, GROUP_RESOURCE_TYPE]


@scim_router.get("/Schemas")
def get_schemas() -> list[ScimSchemaDefinition]:
    """Return SCIM schema definitions (RFC 7643 §7)."""
    return [USER_SCHEMA_DEF, GROUP_SCHEMA_DEF]
