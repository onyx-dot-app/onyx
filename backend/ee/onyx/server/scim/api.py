"""SCIM 2.0 API endpoints (RFC 7644).

This module provides the FastAPI router for SCIM service discovery,
User CRUD, and Group CRUD. Identity providers (Okta, Azure AD) call
these endpoints to provision and manage users and groups.

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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ee.onyx.db.scim import ScimDAL
from ee.onyx.server.scim.auth import verify_scim_token
from ee.onyx.server.scim.filtering import parse_scim_filter
from ee.onyx.server.scim.models import ScimEmail
from ee.onyx.server.scim.models import ScimError
from ee.onyx.server.scim.models import ScimGroupMember
from ee.onyx.server.scim.models import ScimGroupResource
from ee.onyx.server.scim.models import ScimListResponse
from ee.onyx.server.scim.models import ScimMeta
from ee.onyx.server.scim.models import ScimName
from ee.onyx.server.scim.models import ScimPatchRequest
from ee.onyx.server.scim.models import ScimResourceType
from ee.onyx.server.scim.models import ScimSchemaDefinition
from ee.onyx.server.scim.models import ScimServiceProviderConfig
from ee.onyx.server.scim.models import ScimUserResource
from ee.onyx.server.scim.patch import apply_group_patch
from ee.onyx.server.scim.patch import apply_user_patch
from ee.onyx.server.scim.patch import ScimPatchError
from ee.onyx.server.scim.schema_definitions import GROUP_RESOURCE_TYPE
from ee.onyx.server.scim.schema_definitions import GROUP_SCHEMA_DEF
from ee.onyx.server.scim.schema_definitions import SERVICE_PROVIDER_CONFIG
from ee.onyx.server.scim.schema_definitions import USER_RESOURCE_TYPE
from ee.onyx.server.scim.schema_definitions import USER_SCHEMA_DEF
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import ScimToken
from onyx.db.models import User
from onyx.db.models import UserGroup
from onyx.db.models import UserRole
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop


# NOTE: All URL paths in this router (/ServiceProviderConfig, /ResourceTypes,
# /Schemas, /Users, /Groups) are mandated by the SCIM spec (RFC 7643/7644).
# IdPs like Okta and Azure AD hardcode these exact paths, so they cannot be
# changed to kebab-case.
scim_router = APIRouter(prefix="/scim/v2", tags=["SCIM"])

_pw_helper = PasswordHelper()


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


def _check_seat_availability(dal: ScimDAL) -> str | None:
    """Return an error message if seat limit is reached, else None."""
    check_fn = fetch_ee_implementation_or_noop(
        "onyx.db.license", "check_seat_availability", None
    )
    if check_fn is None:
        return None
    result = check_fn(dal.session, seats_needed=1)
    if not result.available:
        return result.error_message or "Seat limit reached"
    return None


def _fetch_user_or_404(user_id: str, dal: ScimDAL) -> User | JSONResponse:
    """Parse *user_id* as UUID, look up the user, or return a 404 error."""
    try:
        uid = UUID(user_id)
    except ValueError:
        return _scim_error_response(404, f"User {user_id} not found")
    user = dal.get_user(uid)
    if not user:
        return _scim_error_response(404, f"User {user_id} not found")
    return user


def _scim_name_to_str(name: ScimName | None) -> str | None:
    """Extract a display name string from a SCIM name object.

    Returns None if no name is provided, so the caller can decide
    whether to update the user's personal_name.
    """
    if not name:
        return None
    return name.formatted or " ".join(
        part for part in [name.givenName, name.familyName] if part
    )


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
    dal.update_token_last_used(_token.id)

    try:
        scim_filter = parse_scim_filter(filter)
    except ValueError as e:
        return _scim_error_response(400, str(e))

    try:
        users_with_ext_ids, total = dal.list_users(scim_filter, startIndex, count)
    except ValueError as e:
        return _scim_error_response(400, str(e))

    resources: list[ScimUserResource | ScimGroupResource] = [
        _user_to_scim(user, ext_id) for user, ext_id in users_with_ext_ids
    ]

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
    dal = ScimDAL(db_session)
    dal.update_token_last_used(_token.id)

    result = _fetch_user_or_404(user_id, dal)
    if isinstance(result, JSONResponse):
        return result
    user = result

    mapping = dal.get_user_mapping_by_user_id(user.id)
    return _user_to_scim(user, mapping.external_id if mapping else None)


@scim_router.post("/Users", status_code=201, response_model=None)
def create_user(
    user_resource: ScimUserResource,
    _token: ScimToken = Depends(verify_scim_token),
    db_session: Session = Depends(get_session),
) -> ScimUserResource | JSONResponse:
    """Create a new user from a SCIM provisioning request."""
    dal = ScimDAL(db_session)
    dal.update_token_last_used(_token.id)

    email = user_resource.userName.strip().lower()

    # externalId is how the IdP correlates this user on subsequent requests.
    # Without it, the IdP can't find the user and will try to re-create,
    # hitting a 409 conflict — so we require it up front.
    if not user_resource.externalId:
        return _scim_error_response(400, "externalId is required")

    # Enforce seat limit
    seat_error = _check_seat_availability(dal)
    if seat_error:
        return _scim_error_response(403, seat_error)

    # Check for existing user
    if dal.get_user_by_email(email):
        return _scim_error_response(409, f"User with email {email} already exists")

    # Create user with a random password (SCIM users authenticate via IdP)
    personal_name = _scim_name_to_str(user_resource.name)
    user = User(
        email=email,
        hashed_password=_pw_helper.hash(_pw_helper.generate()),
        role=UserRole.BASIC,
        is_active=user_resource.active,
        is_verified=True,
        personal_name=personal_name,
    )

    try:
        dal.add_user(user)
    except IntegrityError:
        dal.rollback()
        return _scim_error_response(409, f"User with email {email} already exists")

    # Create SCIM mapping (externalId is validated above, always present)
    external_id = user_resource.externalId
    dal.create_user_mapping(external_id=external_id, user_id=user.id)

    dal.commit()

    return _user_to_scim(user, external_id)


@scim_router.put("/Users/{user_id}", response_model=None)
def replace_user(
    user_id: str,
    user_resource: ScimUserResource,
    _token: ScimToken = Depends(verify_scim_token),
    db_session: Session = Depends(get_session),
) -> ScimUserResource | JSONResponse:
    """Replace a user entirely (RFC 7644 §3.5.1)."""
    dal = ScimDAL(db_session)
    dal.update_token_last_used(_token.id)

    result = _fetch_user_or_404(user_id, dal)
    if isinstance(result, JSONResponse):
        return result
    user = result

    # Handle activation (need seat check) / deactivation
    if user_resource.active and not user.is_active:
        seat_error = _check_seat_availability(dal)
        if seat_error:
            return _scim_error_response(403, seat_error)

    dal.update_user(
        user,
        email=user_resource.userName.strip().lower(),
        is_active=user_resource.active,
        personal_name=_scim_name_to_str(user_resource.name),
    )

    new_external_id = user_resource.externalId
    dal.sync_user_external_id(user.id, new_external_id)

    dal.commit()

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
    dal = ScimDAL(db_session)
    dal.update_token_last_used(_token.id)

    result = _fetch_user_or_404(user_id, dal)
    if isinstance(result, JSONResponse):
        return result
    user = result

    mapping = dal.get_user_mapping_by_user_id(user.id)
    external_id = mapping.external_id if mapping else None

    current = _user_to_scim(user, external_id)

    try:
        patched = apply_user_patch(patch_request.Operations, current)
    except ScimPatchError as e:
        return _scim_error_response(e.status, e.detail)

    # Apply changes back to the DB model
    if patched.active != user.is_active:
        if patched.active:
            seat_error = _check_seat_availability(dal)
            if seat_error:
                return _scim_error_response(403, seat_error)

    dal.update_user(
        user,
        email=(
            patched.userName.strip().lower()
            if patched.userName.lower() != user.email
            else None
        ),
        is_active=patched.active if patched.active != user.is_active else None,
        personal_name=_scim_name_to_str(patched.name),
    )

    dal.sync_user_external_id(user.id, patched.externalId)

    dal.commit()

    return _user_to_scim(user, patched.externalId)


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
    dal = ScimDAL(db_session)
    dal.update_token_last_used(_token.id)

    result = _fetch_user_or_404(user_id, dal)
    if isinstance(result, JSONResponse):
        return result
    user = result

    dal.deactivate_user(user)

    mapping = dal.get_user_mapping_by_user_id(user.id)
    if mapping:
        dal.delete_user_mapping(mapping.id)

    dal.commit()

    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Group helpers
# ---------------------------------------------------------------------------


def _group_to_scim(
    group: UserGroup,
    members: list[tuple[UUID, str | None]],
    external_id: str | None = None,
) -> ScimGroupResource:
    """Convert an Onyx UserGroup to a SCIM Group resource."""
    scim_members = [
        ScimGroupMember(value=str(uid), display=email) for uid, email in members
    ]
    return ScimGroupResource(
        id=str(group.id),
        externalId=external_id,
        displayName=group.name,
        members=scim_members,
        meta=ScimMeta(resourceType="Group"),
    )


def _fetch_group_or_404(group_id: str, dal: ScimDAL) -> UserGroup | JSONResponse:
    """Parse *group_id* as int, look up the group, or return a 404 error."""
    try:
        gid = int(group_id)
    except ValueError:
        return _scim_error_response(404, f"Group {group_id} not found")
    group = dal.get_group(gid)
    if not group:
        return _scim_error_response(404, f"Group {group_id} not found")
    return group


def _parse_member_uuids(
    members: list[ScimGroupMember],
) -> tuple[list[UUID], str | None]:
    """Parse member value strings to UUIDs.

    Returns (uuid_list, error_message). error_message is None on success.
    """
    uuids: list[UUID] = []
    for m in members:
        try:
            uuids.append(UUID(m.value))
        except ValueError:
            return [], f"Invalid member ID: {m.value}"
    return uuids, None


def _validate_and_parse_members(
    members: list[ScimGroupMember], dal: ScimDAL
) -> tuple[list[UUID], str | None]:
    """Parse and validate member UUIDs exist in the database.

    Returns (uuid_list, error_message). error_message is None on success.
    """
    uuids, err = _parse_member_uuids(members)
    if err:
        return [], err

    if uuids:
        missing = dal.validate_member_ids(uuids)
        if missing:
            return [], f"Member(s) not found: {', '.join(str(u) for u in missing)}"

    return uuids, None


# ---------------------------------------------------------------------------
# Group CRUD (RFC 7644 §3)
# ---------------------------------------------------------------------------


@scim_router.get("/Groups", response_model=None)
def list_groups(
    filter: str | None = Query(None),
    startIndex: int = Query(1, ge=1),
    count: int = Query(100, ge=0, le=500),
    _token: ScimToken = Depends(verify_scim_token),
    db_session: Session = Depends(get_session),
) -> ScimListResponse | JSONResponse:
    """List groups with optional SCIM filter and pagination."""
    dal = ScimDAL(db_session)
    dal.update_token_last_used(_token.id)

    try:
        scim_filter = parse_scim_filter(filter)
    except ValueError as e:
        return _scim_error_response(400, str(e))

    try:
        groups_with_ext_ids, total = dal.list_groups(scim_filter, startIndex, count)
    except ValueError as e:
        return _scim_error_response(400, str(e))

    resources: list[ScimUserResource | ScimGroupResource] = [
        _group_to_scim(group, dal.get_group_members(group.id), ext_id)
        for group, ext_id in groups_with_ext_ids
    ]

    return ScimListResponse(
        totalResults=total,
        startIndex=startIndex,
        itemsPerPage=count,
        Resources=resources,
    )


@scim_router.get("/Groups/{group_id}", response_model=None)
def get_group(
    group_id: str,
    _token: ScimToken = Depends(verify_scim_token),
    db_session: Session = Depends(get_session),
) -> ScimGroupResource | JSONResponse:
    """Get a single group by ID."""
    dal = ScimDAL(db_session)
    dal.update_token_last_used(_token.id)

    result = _fetch_group_or_404(group_id, dal)
    if isinstance(result, JSONResponse):
        return result
    group = result

    mapping = dal.get_group_mapping_by_group_id(group.id)
    members = dal.get_group_members(group.id)

    return _group_to_scim(group, members, mapping.external_id if mapping else None)


@scim_router.post("/Groups", status_code=201, response_model=None)
def create_group(
    group_resource: ScimGroupResource,
    _token: ScimToken = Depends(verify_scim_token),
    db_session: Session = Depends(get_session),
) -> ScimGroupResource | JSONResponse:
    """Create a new group from a SCIM provisioning request."""
    dal = ScimDAL(db_session)
    dal.update_token_last_used(_token.id)

    if dal.get_group_by_name(group_resource.displayName):
        return _scim_error_response(
            409, f"Group with name '{group_resource.displayName}' already exists"
        )

    member_uuids, err = _validate_and_parse_members(group_resource.members, dal)
    if err:
        return _scim_error_response(400, err)

    db_group = UserGroup(
        name=group_resource.displayName,
        is_up_to_date=True,
        time_last_modified_by_user=func.now(),
    )
    try:
        dal.add_group(db_group)
    except IntegrityError:
        dal.rollback()
        return _scim_error_response(
            409, f"Group with name '{group_resource.displayName}' already exists"
        )

    dal.upsert_group_members(db_group.id, member_uuids)

    external_id = group_resource.externalId
    if external_id:
        dal.create_group_mapping(external_id=external_id, user_group_id=db_group.id)

    dal.commit()

    members = dal.get_group_members(db_group.id)
    return _group_to_scim(db_group, members, external_id)


@scim_router.put("/Groups/{group_id}", response_model=None)
def replace_group(
    group_id: str,
    group_resource: ScimGroupResource,
    _token: ScimToken = Depends(verify_scim_token),
    db_session: Session = Depends(get_session),
) -> ScimGroupResource | JSONResponse:
    """Replace a group entirely (RFC 7644 §3.5.1)."""
    dal = ScimDAL(db_session)
    dal.update_token_last_used(_token.id)

    result = _fetch_group_or_404(group_id, dal)
    if isinstance(result, JSONResponse):
        return result
    group = result

    member_uuids, err = _validate_and_parse_members(group_resource.members, dal)
    if err:
        return _scim_error_response(400, err)

    dal.update_group(group, name=group_resource.displayName)
    dal.replace_group_members(group.id, member_uuids)
    dal.sync_group_external_id(group.id, group_resource.externalId)

    dal.commit()

    members = dal.get_group_members(group.id)
    return _group_to_scim(group, members, group_resource.externalId)


@scim_router.patch("/Groups/{group_id}", response_model=None)
def patch_group(
    group_id: str,
    patch_request: ScimPatchRequest,
    _token: ScimToken = Depends(verify_scim_token),
    db_session: Session = Depends(get_session),
) -> ScimGroupResource | JSONResponse:
    """Partially update a group (RFC 7644 §3.5.2).

    Handles member add/remove operations from Okta and Azure AD.
    """
    dal = ScimDAL(db_session)
    dal.update_token_last_used(_token.id)

    result = _fetch_group_or_404(group_id, dal)
    if isinstance(result, JSONResponse):
        return result
    group = result

    mapping = dal.get_group_mapping_by_group_id(group.id)
    external_id = mapping.external_id if mapping else None

    current_members = dal.get_group_members(group.id)
    current = _group_to_scim(group, current_members, external_id)

    try:
        patched, added_ids, removed_ids = apply_group_patch(
            patch_request.Operations, current
        )
    except ScimPatchError as e:
        return _scim_error_response(e.status, e.detail)

    new_name = patched.displayName if patched.displayName != group.name else None
    dal.update_group(group, name=new_name)

    if added_ids:
        add_uuids = [UUID(mid) for mid in added_ids if _is_valid_uuid(mid)]
        if add_uuids:
            missing = dal.validate_member_ids(add_uuids)
            if missing:
                return _scim_error_response(
                    400,
                    f"Member(s) not found: {', '.join(str(u) for u in missing)}",
                )
            dal.upsert_group_members(group.id, add_uuids)

    if removed_ids:
        remove_uuids = [UUID(mid) for mid in removed_ids if _is_valid_uuid(mid)]
        dal.remove_group_members(group.id, remove_uuids)

    dal.sync_group_external_id(group.id, patched.externalId)
    dal.commit()

    members = dal.get_group_members(group.id)
    return _group_to_scim(group, members, patched.externalId)


@scim_router.delete("/Groups/{group_id}", status_code=204, response_model=None)
def delete_group(
    group_id: str,
    _token: ScimToken = Depends(verify_scim_token),
    db_session: Session = Depends(get_session),
) -> Response | JSONResponse:
    """Delete a group (RFC 7644 §3.6)."""
    dal = ScimDAL(db_session)
    dal.update_token_last_used(_token.id)

    result = _fetch_group_or_404(group_id, dal)
    if isinstance(result, JSONResponse):
        return result
    group = result

    mapping = dal.get_group_mapping_by_group_id(group.id)
    if mapping:
        dal.delete_group_mapping(mapping.id)

    dal.delete_group_with_members(group)
    dal.commit()

    return Response(status_code=204)


def _is_valid_uuid(value: str) -> bool:
    """Check if a string is a valid UUID."""
    try:
        UUID(value)
        return True
    except ValueError:
        return False
