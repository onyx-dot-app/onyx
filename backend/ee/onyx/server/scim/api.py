"""SCIM 2.0 API endpoints (RFC 7644).

This module provides the FastAPI router for SCIM service discovery.
Identity providers query these endpoints during initial setup to learn
which SCIM features are supported and which resource types are available.

Service discovery endpoints are unauthenticated — IdPs may probe them
before bearer token configuration is complete.
"""

from __future__ import annotations

from fastapi import APIRouter

from ee.onyx.server.scim.models import SCIM_GROUP_SCHEMA
from ee.onyx.server.scim.models import SCIM_USER_SCHEMA
from ee.onyx.server.scim.models import ScimResourceType
from ee.onyx.server.scim.models import ScimServiceProviderConfig


scim_router = APIRouter(prefix="/scim/v2", tags=["SCIM"])


# ---------------------------------------------------------------------------
# Service Discovery (RFC 7643 §4, §5, §6)
# ---------------------------------------------------------------------------

# Pre-built static responses — constructed once at import time.
_SERVICE_PROVIDER_CONFIG = ScimServiceProviderConfig()

_USER_RESOURCE_TYPE = ScimResourceType.model_validate(
    {
        "id": "User",
        "name": "User",
        "endpoint": "/scim/v2/Users",
        "description": "SCIM User resource",
        "schema": SCIM_USER_SCHEMA,
    }
)

_GROUP_RESOURCE_TYPE = ScimResourceType.model_validate(
    {
        "id": "Group",
        "name": "Group",
        "endpoint": "/scim/v2/Groups",
        "description": "SCIM Group resource",
        "schema": SCIM_GROUP_SCHEMA,
    }
)

_SCHEMAS_RESPONSE: list[dict] = [
    {
        "id": SCIM_USER_SCHEMA,
        "name": "User",
        "description": "SCIM core User schema",
    },
    {
        "id": SCIM_GROUP_SCHEMA,
        "name": "Group",
        "description": "SCIM core Group schema",
    },
]


@scim_router.get("/ServiceProviderConfig")
def get_service_provider_config() -> ScimServiceProviderConfig:
    """Advertise supported SCIM features (RFC 7643 §5)."""
    return _SERVICE_PROVIDER_CONFIG


@scim_router.get("/ResourceTypes")
def get_resource_types() -> list[ScimResourceType]:
    """List available SCIM resource types (RFC 7643 §6)."""
    return [_USER_RESOURCE_TYPE, _GROUP_RESOURCE_TYPE]


@scim_router.get("/Schemas")
def get_schemas() -> list[dict]:
    """Return SCIM schema definitions (RFC 7643 §7)."""
    return _SCHEMAS_RESPONSE
