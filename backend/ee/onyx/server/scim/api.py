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
from ee.onyx.server.scim.models import SCIM_LIST_RESPONSE_SCHEMA
from ee.onyx.server.scim.models import ScimError
from ee.onyx.server.scim.models import ScimGroupMember
from ee.onyx.server.scim.models import ScimGroupResource
from ee.onyx.server.scim.models import ScimListResponse
from ee.onyx.server.scim.models import ScimName
from ee.onyx.server.scim.models import ScimPatchRequest
from ee.onyx.server.scim.models import ScimServiceProviderConfig
from ee.onyx.server.scim.models import ScimUserResource
from ee.onyx.server.scim.patch import apply_group_patch
from ee.onyx.server.scim.patch import apply_user_patch
from ee.onyx.server.scim.patch import ScimPatchError
from ee.onyx.server.scim.providers.base import get_default_provider
from ee.onyx.server.scim.providers.base import ScimProvider
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
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop

logger = setup_logger()


class ScimJSONResponse(JSONResponse):
    """JSONResponse with Content-Type: application/scim+json (RFC 7644 §3.1)."""

    media_type = "application/scim+json"


# NOTE: All URL paths in this router (/ServiceProviderConfig, /ResourceTypes,
# /Schemas, /Users, /Groups) are mandated by the SCIM spec (RFC 7643/7644).
# IdPs like Okta and Azure AD hardcode these exact paths, so they cannot be
# changed to kebab-case.


scim_router = APIRouter(prefix="/scim/v2", tags=["SCIM"])

_pw_helper = PasswordHelper()


def _get_provider(
    _token: ScimToken = Depends(verify_scim_token),
) -> ScimProvider:
    """Resolve the SCIM provider for the current request.

    Currently returns OktaProvider for all requests. When multi-provider
    support is added (ENG-3652), this will resolve based on token metadata
    or tenant configuration — no endpoint changes required.
    """
    return get_default_provider()


# ---------------------------------------------------------------------------
# Service Discovery Endpoints (unauthenticated)
# ---------------------------------------------------------------------------


@scim_router.get("/ServiceProviderConfig")
def get_service_provider_config() -> ScimServiceProviderConfig:
    """Advertise supported SCIM features (RFC 7643 §5)."""
    return SERVICE_PROVIDER_CONFIG


@scim_router.get("/ResourceTypes")
def get_resource_types() -> ScimJSONResponse:
    """List available SCIM resource types (RFC 7643 §6).

    Wrapped in a ListResponse envelope (RFC 7644 §3.4.2) because IdPs
    like Entra ID expect a JSON object, not a bare array.
    """
    resources = [USER_RESOURCE_TYPE, GROUP_RESOURCE_TYPE]
    return ScimJSONResponse(
        content={
            "schemas": [SCIM_LIST_RESPONSE_SCHEMA],
            "totalResults": len(resources),
            "Resources": [
                r.model_dump(exclude_none=True, by_alias=True) for r in resources
            ],
        }
    )


@scim_router.get("/Schemas")
def get_schemas() -> ScimJSONResponse:
    """Return SCIM schema definitions (RFC 7643 §7).

    Wrapped in a ListResponse envelope (RFC 7644 §3.4.2) because IdPs
    like Entra ID expect a JSON object, not a bare array.
    """
    schemas = [USER_SCHEMA_DEF, GROUP_SCHEMA_DEF]
    return ScimJSONResponse(
        content={
            "schemas": [SCIM_LIST_RESPONSE_SCHEMA],
            "totalResults": len(schemas),
            "Resources": [s.model_dump(exclude_none=True) for s in schemas],
        }
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scim_error_response(status: int, detail: str) -> ScimJSONResponse:
    """Build a SCIM-compliant error response (RFC 7644 §3.12)."""
    logger.warning("SCIM error response: status=%s detail=%s", status, detail)
    body = ScimError(status=str(status), detail=detail)
    return ScimJSONResponse(
        status_code=status,
        content=body.model_dump(exclude_none=True),
    )


def _parse_excluded_attributes(raw: str | None) -> set[str]:
    """Parse the ``excludedAttributes`` query parameter (RFC 7644 §3.4.2.5).

    Returns a set of lowercased attribute names to omit from responses.
    """
    if not raw:
        return set()
    return {attr.strip().lower() for attr in raw.split(",") if attr.strip()}


def _apply_exclusions(
    resource: ScimUserResource | ScimGroupResource,
    excluded: set[str],
) -> dict:
    """Serialize a SCIM resource, omitting attributes the IdP excluded.

    RFC 7644 §3.4.2.5 lets the IdP pass ``?excludedAttributes=groups,emails``
    to reduce response payload size. We strip those fields after serialization
    so the rest of the pipeline doesn't need to know about them.
    """
    data = resource.model_dump(exclude_none=True, by_alias=True)
    for attr in excluded:
        # Match case-insensitively against the camelCase field names
        keys_to_remove = [k for k in data if k.lower() == attr]
        for k in keys_to_remove:
            del data[k]
    return data


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


def _fetch_user_or_404(user_id: str, dal: ScimDAL) -> User | ScimJSONResponse:
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
    # If the client explicitly provides ``formatted``, prefer it — the client
    # knows what display string it wants. Otherwise build from components.
    if name.formatted:
        return name.formatted
    parts = " ".join(part for part in [name.givenName, name.familyName] if part)
    return parts or None


def _scim_resource_response(
    resource: ScimUserResource | ScimGroupResource | ScimListResponse,
    status_code: int = 200,
) -> ScimJSONResponse:
    """Serialize a SCIM resource as ``application/scim+json``."""
    content = resource.model_dump(exclude_none=True, by_alias=True)
    return ScimJSONResponse(
        status_code=status_code,
        content=content,
    )


def _build_list_response(
    resources: list[ScimUserResource | ScimGroupResource],
    total: int,
    start_index: int,
    count: int,
    excluded: set[str] | None = None,
) -> ScimListResponse | ScimJSONResponse:
    """Build a SCIM list response, optionally applying attribute exclusions.

    RFC 7644 §3.4.2.5 — IdPs may request certain attributes be omitted via
    the ``excludedAttributes`` query parameter.
    """
    if excluded:
        envelope = ScimListResponse(
            totalResults=total,
            startIndex=start_index,
            itemsPerPage=count,
        )
        data = envelope.model_dump(exclude_none=True)
        data["Resources"] = [_apply_exclusions(r, excluded) for r in resources]
        return ScimJSONResponse(content=data)

    return _scim_resource_response(
        ScimListResponse(
            totalResults=total,
            startIndex=start_index,
            itemsPerPage=count,
            Resources=resources,
        )
    )


# ---------------------------------------------------------------------------
# User CRUD (RFC 7644 §3)
# ---------------------------------------------------------------------------


@scim_router.get("/Users", response_model=None)
def list_users(
    filter: str | None = Query(None),
    excludedAttributes: str | None = None,
    startIndex: int = Query(1, ge=1),
    count: int = Query(100, ge=0, le=500),
    _token: ScimToken = Depends(verify_scim_token),
    provider: ScimProvider = Depends(_get_provider),
    db_session: Session = Depends(get_session),
) -> ScimListResponse | ScimJSONResponse:
    """List users with optional SCIM filter and pagination."""
    dal = ScimDAL(db_session)
    dal.update_token_last_used(_token.id)

    try:
        scim_filter = parse_scim_filter(filter)
    except ValueError as e:
        return _scim_error_response(400, str(e))

    try:
        users_with_mappings, total = dal.list_users(scim_filter, startIndex, count)
    except ValueError as e:
        return _scim_error_response(400, str(e))

    user_groups_map = dal.get_users_groups_batch([u.id for u, _ in users_with_mappings])
    resources: list[ScimUserResource | ScimGroupResource] = [
        provider.build_user_resource(
            user,
            mapping.external_id if mapping else None,
            groups=user_groups_map.get(user.id, []),
            scim_username=mapping.scim_username if mapping else None,
        )
        for user, mapping in users_with_mappings
    ]

    return _build_list_response(
        resources,
        total,
        startIndex,
        count,
        excluded=_parse_excluded_attributes(excludedAttributes),
    )


@scim_router.get("/Users/{user_id}", response_model=None)
def get_user(
    user_id: str,
    excludedAttributes: str | None = None,
    _token: ScimToken = Depends(verify_scim_token),
    provider: ScimProvider = Depends(_get_provider),
    db_session: Session = Depends(get_session),
) -> ScimUserResource | ScimJSONResponse:
    """Get a single user by ID."""
    dal = ScimDAL(db_session)
    dal.update_token_last_used(_token.id)

    result = _fetch_user_or_404(user_id, dal)
    if isinstance(result, ScimJSONResponse):
        return result
    user = result

    mapping = dal.get_user_mapping_by_user_id(user.id)

    resource = provider.build_user_resource(
        user,
        mapping.external_id if mapping else None,
        groups=dal.get_user_groups(user.id),
        scim_username=mapping.scim_username if mapping else None,
    )

    # RFC 7644 §3.4.2.5 — IdP may request certain attributes be omitted
    excluded = _parse_excluded_attributes(excludedAttributes)
    if excluded:
        return ScimJSONResponse(content=_apply_exclusions(resource, excluded))

    return _scim_resource_response(resource)


@scim_router.post("/Users", status_code=201, response_model=None)
def create_user(
    user_resource: ScimUserResource,
    _token: ScimToken = Depends(verify_scim_token),
    provider: ScimProvider = Depends(_get_provider),
    db_session: Session = Depends(get_session),
) -> ScimUserResource | ScimJSONResponse:
    """Create a new user from a SCIM provisioning request."""
    dal = ScimDAL(db_session)
    dal.update_token_last_used(_token.id)

    email = user_resource.userName.strip()

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
    scim_username = user_resource.userName.strip()
    dal.create_user_mapping(
        external_id=external_id, user_id=user.id, scim_username=scim_username
    )

    dal.commit()

    return _scim_resource_response(
        provider.build_user_resource(user, external_id, scim_username=scim_username),
        status_code=201,
    )


@scim_router.put("/Users/{user_id}", response_model=None)
def replace_user(
    user_id: str,
    user_resource: ScimUserResource,
    _token: ScimToken = Depends(verify_scim_token),
    provider: ScimProvider = Depends(_get_provider),
    db_session: Session = Depends(get_session),
) -> ScimUserResource | ScimJSONResponse:
    """Replace a user entirely (RFC 7644 §3.5.1)."""
    dal = ScimDAL(db_session)
    dal.update_token_last_used(_token.id)

    result = _fetch_user_or_404(user_id, dal)
    if isinstance(result, ScimJSONResponse):
        return result
    user = result

    # Handle activation (need seat check) / deactivation
    if user_resource.active and not user.is_active:
        seat_error = _check_seat_availability(dal)
        if seat_error:
            return _scim_error_response(403, seat_error)

    personal_name = _scim_name_to_str(user_resource.name)

    dal.update_user(
        user,
        email=user_resource.userName.strip(),
        is_active=user_resource.active,
        personal_name=personal_name,
    )

    new_external_id = user_resource.externalId
    scim_username = user_resource.userName.strip()
    dal.sync_user_external_id(user.id, new_external_id, scim_username=scim_username)

    dal.commit()

    return _scim_resource_response(
        provider.build_user_resource(
            user,
            new_external_id,
            groups=dal.get_user_groups(user.id),
            scim_username=scim_username,
        )
    )


@scim_router.patch("/Users/{user_id}", response_model=None)
def patch_user(
    user_id: str,
    patch_request: ScimPatchRequest,
    _token: ScimToken = Depends(verify_scim_token),
    provider: ScimProvider = Depends(_get_provider),
    db_session: Session = Depends(get_session),
) -> ScimUserResource | ScimJSONResponse:
    """Partially update a user (RFC 7644 §3.5.2).

    This is the primary endpoint for user deprovisioning — Okta sends
    ``PATCH {"active": false}`` rather than DELETE.
    """
    dal = ScimDAL(db_session)
    dal.update_token_last_used(_token.id)

    result = _fetch_user_or_404(user_id, dal)
    if isinstance(result, ScimJSONResponse):
        return result
    user = result

    mapping = dal.get_user_mapping_by_user_id(user.id)
    external_id = mapping.external_id if mapping else None
    current_scim_username = mapping.scim_username if mapping else None

    current = provider.build_user_resource(
        user,
        external_id,
        groups=dal.get_user_groups(user.id),
        scim_username=current_scim_username,
    )

    try:
        patched = apply_user_patch(
            patch_request.Operations, current, provider.ignored_patch_paths
        )
    except ScimPatchError as e:
        return _scim_error_response(e.status, e.detail)

    # Apply changes back to the DB model
    if patched.active != user.is_active:
        if patched.active:
            seat_error = _check_seat_availability(dal)
            if seat_error:
                return _scim_error_response(403, seat_error)

    # Track the scim_username — if userName was patched, update it
    new_scim_username = patched.userName.strip() if patched.userName else None

    # If displayName was explicitly patched (different from the original), use
    # it as personal_name directly.  Otherwise, derive from name components.
    personal_name: str | None
    if patched.displayName and patched.displayName != current.displayName:
        personal_name = patched.displayName
    else:
        personal_name = _scim_name_to_str(patched.name)

    dal.update_user(
        user,
        email=(
            patched.userName.strip()
            if patched.userName.strip().lower() != user.email.lower()
            else None
        ),
        is_active=patched.active if patched.active != user.is_active else None,
        personal_name=personal_name,
    )

    dal.sync_user_external_id(
        user.id, patched.externalId, scim_username=new_scim_username
    )

    dal.commit()

    return _scim_resource_response(
        provider.build_user_resource(
            user,
            patched.externalId,
            groups=dal.get_user_groups(user.id),
            scim_username=new_scim_username,
        )
    )


@scim_router.delete("/Users/{user_id}", status_code=204, response_model=None)
def delete_user(
    user_id: str,
    _token: ScimToken = Depends(verify_scim_token),
    db_session: Session = Depends(get_session),
) -> Response | ScimJSONResponse:
    """Delete a user (RFC 7644 §3.6).

    Deactivates the user and removes the SCIM mapping. Note that Okta
    typically uses PATCH active=false instead of DELETE.
    A second DELETE returns 404 per RFC 7644 §3.6.
    """
    dal = ScimDAL(db_session)
    dal.update_token_last_used(_token.id)

    result = _fetch_user_or_404(user_id, dal)
    if isinstance(result, ScimJSONResponse):
        return result
    user = result

    # If no SCIM mapping exists, the user was already deleted from
    # SCIM's perspective — return 404 per RFC 7644 §3.6.
    mapping = dal.get_user_mapping_by_user_id(user.id)
    if not mapping:
        return _scim_error_response(404, f"User {user_id} not found")

    dal.deactivate_user(user)
    dal.delete_user_mapping(mapping.id)

    dal.commit()

    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Group helpers
# ---------------------------------------------------------------------------


def _fetch_group_or_404(group_id: str, dal: ScimDAL) -> UserGroup | ScimJSONResponse:
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
    excludedAttributes: str | None = None,
    startIndex: int = Query(1, ge=1),
    count: int = Query(100, ge=0, le=500),
    _token: ScimToken = Depends(verify_scim_token),
    provider: ScimProvider = Depends(_get_provider),
    db_session: Session = Depends(get_session),
) -> ScimListResponse | ScimJSONResponse:
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
        provider.build_group_resource(group, dal.get_group_members(group.id), ext_id)
        for group, ext_id in groups_with_ext_ids
    ]

    return _build_list_response(
        resources,
        total,
        startIndex,
        count,
        excluded=_parse_excluded_attributes(excludedAttributes),
    )


@scim_router.get("/Groups/{group_id}", response_model=None)
def get_group(
    group_id: str,
    excludedAttributes: str | None = None,
    _token: ScimToken = Depends(verify_scim_token),
    provider: ScimProvider = Depends(_get_provider),
    db_session: Session = Depends(get_session),
) -> ScimGroupResource | ScimJSONResponse:
    """Get a single group by ID."""
    dal = ScimDAL(db_session)
    dal.update_token_last_used(_token.id)

    result = _fetch_group_or_404(group_id, dal)
    if isinstance(result, ScimJSONResponse):
        return result
    group = result

    mapping = dal.get_group_mapping_by_group_id(group.id)
    members = dal.get_group_members(group.id)

    resource = provider.build_group_resource(
        group, members, mapping.external_id if mapping else None
    )

    # RFC 7644 §3.4.2.5 — IdP may request certain attributes be omitted
    excluded = _parse_excluded_attributes(excludedAttributes)
    if excluded:
        return ScimJSONResponse(content=_apply_exclusions(resource, excluded))

    return _scim_resource_response(resource)


@scim_router.post("/Groups", status_code=201, response_model=None)
def create_group(
    group_resource: ScimGroupResource,
    _token: ScimToken = Depends(verify_scim_token),
    provider: ScimProvider = Depends(_get_provider),
    db_session: Session = Depends(get_session),
) -> ScimGroupResource | ScimJSONResponse:
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
    return _scim_resource_response(
        provider.build_group_resource(db_group, members, external_id),
        status_code=201,
    )


@scim_router.put("/Groups/{group_id}", response_model=None)
def replace_group(
    group_id: str,
    group_resource: ScimGroupResource,
    _token: ScimToken = Depends(verify_scim_token),
    provider: ScimProvider = Depends(_get_provider),
    db_session: Session = Depends(get_session),
) -> ScimGroupResource | ScimJSONResponse:
    """Replace a group entirely (RFC 7644 §3.5.1)."""
    dal = ScimDAL(db_session)
    dal.update_token_last_used(_token.id)

    result = _fetch_group_or_404(group_id, dal)
    if isinstance(result, ScimJSONResponse):
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
    return _scim_resource_response(
        provider.build_group_resource(group, members, group_resource.externalId)
    )


@scim_router.patch("/Groups/{group_id}", response_model=None)
def patch_group(
    group_id: str,
    patch_request: ScimPatchRequest,
    _token: ScimToken = Depends(verify_scim_token),
    provider: ScimProvider = Depends(_get_provider),
    db_session: Session = Depends(get_session),
) -> ScimGroupResource | ScimJSONResponse:
    """Partially update a group (RFC 7644 §3.5.2).

    Handles member add/remove operations from Okta and Azure AD.
    """
    dal = ScimDAL(db_session)
    dal.update_token_last_used(_token.id)

    result = _fetch_group_or_404(group_id, dal)
    if isinstance(result, ScimJSONResponse):
        return result
    group = result

    mapping = dal.get_group_mapping_by_group_id(group.id)
    external_id = mapping.external_id if mapping else None

    current_members = dal.get_group_members(group.id)
    current = provider.build_group_resource(group, current_members, external_id)

    try:
        patched, added_ids, removed_ids = apply_group_patch(
            patch_request.Operations, current, provider.ignored_patch_paths
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
    return _scim_resource_response(
        provider.build_group_resource(group, members, patched.externalId)
    )


@scim_router.delete("/Groups/{group_id}", status_code=204, response_model=None)
def delete_group(
    group_id: str,
    _token: ScimToken = Depends(verify_scim_token),
    db_session: Session = Depends(get_session),
) -> Response | ScimJSONResponse:
    """Delete a group (RFC 7644 §3.6)."""
    dal = ScimDAL(db_session)
    dal.update_token_last_used(_token.id)

    result = _fetch_group_or_404(group_id, dal)
    if isinstance(result, ScimJSONResponse):
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
