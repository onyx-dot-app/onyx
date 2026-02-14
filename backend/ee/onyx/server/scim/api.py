"""SCIM 2.0 API endpoints (RFC 7644).

This module provides the FastAPI router for SCIM service discovery and
User resource CRUD. Identity providers (Okta, Azure AD) call these
endpoints to provision and manage users.

Service discovery endpoints are unauthenticated — IdPs may probe them
before bearer token configuration is complete. All other endpoints
require a valid SCIM bearer token.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from fastapi import Response
from fastapi.responses import JSONResponse
from fastapi_users.password import PasswordHelper
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from ee.onyx.db.scim import ScimDAL
from ee.onyx.server.scim.auth import verify_scim_token
from ee.onyx.server.scim.filtering import parse_scim_filter
from ee.onyx.server.scim.filtering import ScimFilterOperator
from ee.onyx.server.scim.models import SCIM_GROUP_SCHEMA
from ee.onyx.server.scim.models import SCIM_USER_SCHEMA
from ee.onyx.server.scim.models import ScimEmail
from ee.onyx.server.scim.models import ScimError
from ee.onyx.server.scim.models import ScimGroupResource
from ee.onyx.server.scim.models import ScimListResponse
from ee.onyx.server.scim.models import ScimMeta
from ee.onyx.server.scim.models import ScimName
from ee.onyx.server.scim.models import ScimPatchRequest
from ee.onyx.server.scim.models import ScimResourceType
from ee.onyx.server.scim.models import ScimServiceProviderConfig
from ee.onyx.server.scim.models import ScimUserResource
from ee.onyx.server.scim.patch import apply_user_patch
from ee.onyx.server.scim.patch import ScimPatchError
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import ScimToken
from onyx.db.models import User
from onyx.db.models import UserRole
from onyx.db.users import fetch_user_by_id
from onyx.db.users import get_user_by_email
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop


scim_router = APIRouter(prefix="/scim/v2", tags=["SCIM"])

_pw_helper = PasswordHelper()


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scim_error_response(status: int, detail: str) -> JSONResponse:
    """Build a SCIM-compliant error response (RFC 7644 §3.12)."""
    body = ScimError(status=str(status), detail=detail)
    return JSONResponse(
        status_code=status,
        content=body.model_dump(exclude_none=True),
    )


def _user_to_scim(user: User, external_id: str | None = None) -> ScimUserResource:
    """Convert an Onyx User to a SCIM User resource representation."""
    name = None
    if user.personal_name:
        parts = user.personal_name.split(" ", 1)
        name = ScimName(
            givenName=parts[0],
            familyName=parts[1] if len(parts) > 1 else None,
            formatted=user.personal_name,
        )

    return ScimUserResource(
        id=str(user.id),
        externalId=external_id,
        userName=user.email,
        name=name,
        emails=[ScimEmail(value=user.email, type="work", primary=True)],
        active=user.is_active,
        meta=ScimMeta(resourceType="User"),
    )


def _check_seat_availability(db_session: Session) -> str | None:
    """Return an error message if seat limit is reached, else None."""
    check_fn = fetch_ee_implementation_or_noop(
        "onyx.db.license", "check_seat_availability", None
    )
    if check_fn is None:
        return None
    result = check_fn(db_session, seats_needed=1)
    if not result.available:
        return result.error_message or "Seat limit reached"
    return None


def _parse_user_id(user_id: str) -> UUID | None:
    """Parse a string to UUID, returning None on failure."""
    try:
        return UUID(user_id)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# User CRUD (RFC 7644 §3)
# ---------------------------------------------------------------------------


@scim_router.get("/Users", response_model=None)
def list_users(
    filter: str | None = Query(None),
    startIndex: int = Query(1, ge=1),
    count: int = Query(100, ge=0, le=500),
    _token: ScimToken = Depends(verify_scim_token),
    db_session: Session = Depends(get_session),
) -> ScimListResponse | JSONResponse:
    """List users with optional SCIM filter and pagination."""
    dal = ScimDAL(db_session)

    try:
        scim_filter = parse_scim_filter(filter)
    except ValueError as e:
        return _scim_error_response(400, str(e))

    # Base query: exclude system users
    query = select(User).where(
        User.role.notin_([UserRole.SLACK_USER, UserRole.EXT_PERM_USER])
    )

    if scim_filter:
        attr = scim_filter.attribute.lower()
        if attr == "username":
            if scim_filter.operator == ScimFilterOperator.EQUAL:
                query = query.where(func.lower(User.email) == scim_filter.value.lower())
            elif scim_filter.operator == ScimFilterOperator.CONTAINS:
                query = query.where(
                    User.email.ilike(f"%{scim_filter.value}%")  # type: ignore[attr-defined]
                )
            elif scim_filter.operator == ScimFilterOperator.STARTS_WITH:
                query = query.where(
                    User.email.ilike(f"{scim_filter.value}%")  # type: ignore[attr-defined]
                )
        elif attr == "active":
            if scim_filter.value.lower() == "true":
                query = query.where(User.is_active.is_(True))  # type: ignore[attr-defined]
            else:
                query = query.where(User.is_active.is_(False))  # type: ignore[attr-defined]
        elif attr == "externalid":
            mapping = dal.get_user_mapping_by_external_id(scim_filter.value)
            if not mapping:
                return ScimListResponse(
                    totalResults=0,
                    startIndex=startIndex,
                    itemsPerPage=count,
                )
            query = query.where(User.id == mapping.user_id)  # type: ignore[arg-type]
        else:
            return _scim_error_response(
                400, f"Unsupported filter attribute: {scim_filter.attribute}"
            )

    total = db_session.scalar(select(func.count()).select_from(query.subquery())) or 0

    offset = max(startIndex - 1, 0)
    users = list(
        db_session.scalars(
            query.order_by(User.id).offset(offset).limit(count)  # type: ignore[arg-type]
        ).all()
    )

    resources: list[ScimUserResource | ScimGroupResource] = []
    for user in users:
        mapping = dal.get_user_mapping_by_user_id(user.id)
        resources.append(_user_to_scim(user, mapping.external_id if mapping else None))

    return ScimListResponse(
        totalResults=total,
        startIndex=startIndex,
        itemsPerPage=count,
        Resources=resources,
    )


@scim_router.get("/Users/{user_id}", response_model=None)
def get_user(
    user_id: str,
    _token: ScimToken = Depends(verify_scim_token),
    db_session: Session = Depends(get_session),
) -> ScimUserResource | JSONResponse:
    """Get a single user by ID."""
    uid = _parse_user_id(user_id)
    if not uid:
        return _scim_error_response(404, f"User {user_id} not found")

    user = fetch_user_by_id(db_session, uid)
    if not user:
        return _scim_error_response(404, f"User {user_id} not found")

    dal = ScimDAL(db_session)
    mapping = dal.get_user_mapping_by_user_id(uid)

    return _user_to_scim(user, mapping.external_id if mapping else None)


@scim_router.post("/Users", status_code=201, response_model=None)
def create_user(
    user_resource: ScimUserResource,
    _token: ScimToken = Depends(verify_scim_token),
    db_session: Session = Depends(get_session),
) -> ScimUserResource | JSONResponse:
    """Create a new user from a SCIM provisioning request."""
    email = user_resource.userName.strip().lower()

    # Enforce seat limit
    seat_error = _check_seat_availability(db_session)
    if seat_error:
        return _scim_error_response(403, seat_error)

    # Check for existing user
    existing = get_user_by_email(email, db_session)
    if existing:
        return _scim_error_response(409, f"User with email {email} already exists")

    # Create user with a random password (SCIM users authenticate via IdP)
    user = User(
        email=email,
        hashed_password=_pw_helper.hash(_pw_helper.generate()),
        role=UserRole.BASIC,
        is_active=user_resource.active,
        is_verified=True,
    )
    if user_resource.name:
        user.personal_name = user_resource.name.formatted or " ".join(
            part
            for part in [user_resource.name.givenName, user_resource.name.familyName]
            if part
        )

    db_session.add(user)
    db_session.flush()

    # Create SCIM mapping
    dal = ScimDAL(db_session)
    external_id = user_resource.externalId
    if external_id:
        dal.create_user_mapping(external_id=external_id, user_id=user.id)

    db_session.commit()

    return _user_to_scim(user, external_id)


@scim_router.put("/Users/{user_id}", response_model=None)
def replace_user(
    user_id: str,
    user_resource: ScimUserResource,
    _token: ScimToken = Depends(verify_scim_token),
    db_session: Session = Depends(get_session),
) -> ScimUserResource | JSONResponse:
    """Replace a user entirely (RFC 7644 §3.5.1)."""
    uid = _parse_user_id(user_id)
    if not uid:
        return _scim_error_response(404, f"User {user_id} not found")

    user = fetch_user_by_id(db_session, uid)
    if not user:
        return _scim_error_response(404, f"User {user_id} not found")

    # Handle activation (need seat check) / deactivation
    if user_resource.active and not user.is_active:
        seat_error = _check_seat_availability(db_session)
        if seat_error:
            return _scim_error_response(403, seat_error)

    user.email = user_resource.userName.strip().lower()
    user.is_active = user_resource.active
    if user_resource.name:
        user.personal_name = user_resource.name.formatted or " ".join(
            part
            for part in [user_resource.name.givenName, user_resource.name.familyName]
            if part
        )

    # Update external ID mapping
    dal = ScimDAL(db_session)
    mapping = dal.get_user_mapping_by_user_id(uid)
    new_external_id = user_resource.externalId

    if new_external_id:
        if mapping:
            if mapping.external_id != new_external_id:
                dal.update_user_mapping_external_id(mapping.id, new_external_id)
        else:
            dal.create_user_mapping(external_id=new_external_id, user_id=uid)
    elif mapping:
        dal.delete_user_mapping(mapping.id)

    db_session.commit()

    return _user_to_scim(user, new_external_id)


@scim_router.patch("/Users/{user_id}", response_model=None)
def patch_user(
    user_id: str,
    patch_request: ScimPatchRequest,
    _token: ScimToken = Depends(verify_scim_token),
    db_session: Session = Depends(get_session),
) -> ScimUserResource | JSONResponse:
    """Partially update a user (RFC 7644 §3.5.2).

    This is the primary endpoint for user deprovisioning — Okta sends
    ``PATCH {"active": false}`` rather than DELETE.
    """
    uid = _parse_user_id(user_id)
    if not uid:
        return _scim_error_response(404, f"User {user_id} not found")

    user = fetch_user_by_id(db_session, uid)
    if not user:
        return _scim_error_response(404, f"User {user_id} not found")

    dal = ScimDAL(db_session)
    mapping = dal.get_user_mapping_by_user_id(uid)
    external_id = mapping.external_id if mapping else None

    current = _user_to_scim(user, external_id)

    try:
        patched = apply_user_patch(patch_request.Operations, current)
    except ScimPatchError as e:
        return _scim_error_response(e.status, e.detail)

    # Apply changes back to the DB model
    if patched.active != user.is_active:
        if patched.active:
            seat_error = _check_seat_availability(db_session)
            if seat_error:
                return _scim_error_response(403, seat_error)
        user.is_active = patched.active

    if patched.userName.lower() != user.email:
        user.email = patched.userName.strip().lower()

    if patched.name:
        user.personal_name = patched.name.formatted or " ".join(
            part for part in [patched.name.givenName, patched.name.familyName] if part
        )

    if patched.externalId != external_id:
        if patched.externalId:
            if mapping:
                dal.update_user_mapping_external_id(mapping.id, patched.externalId)
            else:
                dal.create_user_mapping(external_id=patched.externalId, user_id=uid)
        elif mapping:
            dal.delete_user_mapping(mapping.id)

    db_session.commit()

    return _user_to_scim(
        user, patched.externalId if patched.externalId else external_id
    )


@scim_router.delete("/Users/{user_id}", status_code=204, response_model=None)
def delete_user(
    user_id: str,
    _token: ScimToken = Depends(verify_scim_token),
    db_session: Session = Depends(get_session),
) -> Response | JSONResponse:
    """Delete a user (RFC 7644 §3.6).

    Deactivates the user and removes the SCIM mapping. Note that Okta
    typically uses PATCH active=false instead of DELETE.
    """
    uid = _parse_user_id(user_id)
    if not uid:
        return _scim_error_response(404, f"User {user_id} not found")

    user = fetch_user_by_id(db_session, uid)
    if not user:
        return _scim_error_response(404, f"User {user_id} not found")

    user.is_active = False

    dal = ScimDAL(db_session)
    mapping = dal.get_user_mapping_by_user_id(uid)
    if mapping:
        dal.delete_user_mapping(mapping.id)

    db_session.commit()

    return Response(status_code=204)
