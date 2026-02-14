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
from sqlalchemy import delete as sa_delete
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ee.onyx.db.scim import ScimDAL
from ee.onyx.server.scim.auth import verify_scim_token
from ee.onyx.server.scim.filtering import parse_scim_filter
from ee.onyx.server.scim.filtering import ScimFilterOperator
from ee.onyx.server.scim.models import SCIM_GROUP_SCHEMA
from ee.onyx.server.scim.models import SCIM_USER_SCHEMA
from ee.onyx.server.scim.models import ScimEmail
from ee.onyx.server.scim.models import ScimError
from ee.onyx.server.scim.models import ScimGroupMember
from ee.onyx.server.scim.models import ScimGroupResource
from ee.onyx.server.scim.models import ScimListResponse
from ee.onyx.server.scim.models import ScimMeta
from ee.onyx.server.scim.models import ScimName
from ee.onyx.server.scim.models import ScimPatchRequest
from ee.onyx.server.scim.models import ScimResourceType
from ee.onyx.server.scim.models import ScimServiceProviderConfig
from ee.onyx.server.scim.models import ScimUserResource
from ee.onyx.server.scim.patch import apply_group_patch
from ee.onyx.server.scim.patch import apply_user_patch
from ee.onyx.server.scim.patch import ScimPatchError
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import ScimToken
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup
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


# ---------------------------------------------------------------------------
# Group helpers
# ---------------------------------------------------------------------------


def _group_to_scim(
    group: UserGroup,
    db_session: Session,
    external_id: str | None = None,
) -> ScimGroupResource:
    """Convert an Onyx UserGroup to a SCIM Group resource."""
    members: list[ScimGroupMember] = []
    relationships = db_session.scalars(
        select(User__UserGroup).where(User__UserGroup.user_group_id == group.id)
    ).all()
    for rel in relationships:
        user = fetch_user_by_id(db_session, rel.user_id) if rel.user_id else None
        members.append(
            ScimGroupMember(
                value=str(rel.user_id),
                display=user.email if user else None,
            )
        )

    return ScimGroupResource(
        id=str(group.id),
        externalId=external_id,
        displayName=group.name,
        members=members,
        meta=ScimMeta(resourceType="Group"),
    )


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

    try:
        scim_filter = parse_scim_filter(filter)
    except ValueError as e:
        return _scim_error_response(400, str(e))

    query = select(UserGroup).where(UserGroup.is_up_for_deletion.is_(False))

    if scim_filter:
        attr = scim_filter.attribute.lower()
        if attr == "displayname":
            if scim_filter.operator == ScimFilterOperator.EQUAL:
                query = query.where(UserGroup.name == scim_filter.value)
            elif scim_filter.operator == ScimFilterOperator.CONTAINS:
                query = query.where(UserGroup.name.ilike(f"%{scim_filter.value}%"))
            elif scim_filter.operator == ScimFilterOperator.STARTS_WITH:
                query = query.where(UserGroup.name.ilike(f"{scim_filter.value}%"))
        elif attr == "externalid":
            mapping = dal.get_group_mapping_by_external_id(scim_filter.value)
            if not mapping:
                return ScimListResponse(
                    totalResults=0,
                    startIndex=startIndex,
                    itemsPerPage=count,
                )
            query = query.where(UserGroup.id == mapping.user_group_id)
        else:
            return _scim_error_response(
                400, f"Unsupported filter attribute: {scim_filter.attribute}"
            )

    total = db_session.scalar(select(func.count()).select_from(query.subquery())) or 0

    offset = max(startIndex - 1, 0)
    groups = list(
        db_session.scalars(
            query.order_by(UserGroup.id).offset(offset).limit(count)
        ).all()
    )

    resources: list[ScimUserResource | ScimGroupResource] = []
    for group in groups:
        mapping = dal.get_group_mapping_by_group_id(group.id)
        resources.append(
            _group_to_scim(group, db_session, mapping.external_id if mapping else None)
        )

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
    try:
        gid = int(group_id)
    except ValueError:
        return _scim_error_response(404, f"Group {group_id} not found")

    group = db_session.get(UserGroup, gid)
    if not group or group.is_up_for_deletion:
        return _scim_error_response(404, f"Group {group_id} not found")

    dal = ScimDAL(db_session)
    mapping = dal.get_group_mapping_by_group_id(gid)

    return _group_to_scim(group, db_session, mapping.external_id if mapping else None)


@scim_router.post("/Groups", status_code=201, response_model=None)
def create_group(
    group_resource: ScimGroupResource,
    _token: ScimToken = Depends(verify_scim_token),
    db_session: Session = Depends(get_session),
) -> ScimGroupResource | JSONResponse:
    """Create a new group from a SCIM provisioning request."""
    # Check for name conflict
    existing = db_session.scalar(
        select(UserGroup).where(UserGroup.name == group_resource.displayName)
    )
    if existing:
        return _scim_error_response(
            409, f"Group with name '{group_resource.displayName}' already exists"
        )

    # Validate member UUIDs
    member_uuids, err = _parse_member_uuids(group_resource.members)
    if err:
        return _scim_error_response(400, err)

    # Create group directly (is_up_to_date=True since SCIM groups have no cc_pairs)
    db_group = UserGroup(
        name=group_resource.displayName,
        is_up_to_date=True,
        time_last_modified_by_user=func.now(),
    )
    db_session.add(db_group)
    db_session.flush()

    # Add member relationships
    if member_uuids:
        db_session.execute(
            pg_insert(User__UserGroup)
            .values(
                [{"user_id": uid, "user_group_id": db_group.id} for uid in member_uuids]
            )
            .on_conflict_do_nothing(
                index_elements=[
                    User__UserGroup.user_group_id,
                    User__UserGroup.user_id,
                ]
            )
        )

    # Create SCIM mapping
    dal = ScimDAL(db_session)
    external_id = group_resource.externalId
    if external_id:
        dal.create_group_mapping(external_id=external_id, user_group_id=db_group.id)

    db_session.commit()

    return _group_to_scim(db_group, db_session, external_id)


@scim_router.put("/Groups/{group_id}", response_model=None)
def replace_group(
    group_id: str,
    group_resource: ScimGroupResource,
    _token: ScimToken = Depends(verify_scim_token),
    db_session: Session = Depends(get_session),
) -> ScimGroupResource | JSONResponse:
    """Replace a group entirely (RFC 7644 §3.5.1)."""
    try:
        gid = int(group_id)
    except ValueError:
        return _scim_error_response(404, f"Group {group_id} not found")

    group = db_session.get(UserGroup, gid)
    if not group or group.is_up_for_deletion:
        return _scim_error_response(404, f"Group {group_id} not found")

    member_uuids, err = _parse_member_uuids(group_resource.members)
    if err:
        return _scim_error_response(400, err)

    group.name = group_resource.displayName
    group.time_last_modified_by_user = func.now()

    # Replace members: remove all, then add new
    db_session.execute(
        sa_delete(User__UserGroup).where(User__UserGroup.user_group_id == gid)
    )

    if member_uuids:
        db_session.execute(
            pg_insert(User__UserGroup)
            .values([{"user_id": uid, "user_group_id": gid} for uid in member_uuids])
            .on_conflict_do_nothing(
                index_elements=[
                    User__UserGroup.user_group_id,
                    User__UserGroup.user_id,
                ]
            )
        )

    # Update external ID mapping
    dal = ScimDAL(db_session)
    mapping = dal.get_group_mapping_by_group_id(gid)
    new_external_id = group_resource.externalId

    if new_external_id:
        if mapping:
            if mapping.external_id != new_external_id:
                mapping.external_id = new_external_id
        else:
            dal.create_group_mapping(external_id=new_external_id, user_group_id=gid)
    elif mapping:
        dal.delete_group_mapping(mapping.id)

    db_session.commit()

    return _group_to_scim(group, db_session, new_external_id)


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
    try:
        gid = int(group_id)
    except ValueError:
        return _scim_error_response(404, f"Group {group_id} not found")

    group = db_session.get(UserGroup, gid)
    if not group or group.is_up_for_deletion:
        return _scim_error_response(404, f"Group {group_id} not found")

    dal = ScimDAL(db_session)
    mapping = dal.get_group_mapping_by_group_id(gid)
    external_id = mapping.external_id if mapping else None

    current = _group_to_scim(group, db_session, external_id)

    try:
        patched, added_ids, removed_ids = apply_group_patch(
            patch_request.Operations, current
        )
    except ScimPatchError as e:
        return _scim_error_response(e.status, e.detail)

    # Apply name change
    if patched.displayName != group.name:
        group.name = patched.displayName

    # Apply member additions
    if added_ids:
        add_uuids: list[UUID] = []
        for mid in added_ids:
            uid = _parse_user_id(mid)
            if uid:
                add_uuids.append(uid)
        if add_uuids:
            db_session.execute(
                pg_insert(User__UserGroup)
                .values([{"user_id": uid, "user_group_id": gid} for uid in add_uuids])
                .on_conflict_do_nothing(
                    index_elements=[
                        User__UserGroup.user_group_id,
                        User__UserGroup.user_id,
                    ]
                )
            )

    # Apply member removals
    if removed_ids:
        remove_uuids: list[UUID] = []
        for mid in removed_ids:
            uid = _parse_user_id(mid)
            if uid:
                remove_uuids.append(uid)
        if remove_uuids:
            db_session.execute(
                sa_delete(User__UserGroup).where(
                    User__UserGroup.user_group_id == gid,
                    User__UserGroup.user_id.in_(remove_uuids),
                )
            )

    # Handle externalId changes
    if patched.externalId != external_id:
        if patched.externalId:
            if mapping:
                mapping.external_id = patched.externalId
            else:
                dal.create_group_mapping(
                    external_id=patched.externalId, user_group_id=gid
                )
        elif mapping:
            dal.delete_group_mapping(mapping.id)

    group.time_last_modified_by_user = func.now()
    db_session.commit()

    return _group_to_scim(
        group,
        db_session,
        patched.externalId if patched.externalId else external_id,
    )


@scim_router.delete("/Groups/{group_id}", status_code=204, response_model=None)
def delete_group(
    group_id: str,
    _token: ScimToken = Depends(verify_scim_token),
    db_session: Session = Depends(get_session),
) -> Response | JSONResponse:
    """Delete a group (RFC 7644 §3.6)."""
    try:
        gid = int(group_id)
    except ValueError:
        return _scim_error_response(404, f"Group {group_id} not found")

    group = db_session.get(UserGroup, gid)
    if not group or group.is_up_for_deletion:
        return _scim_error_response(404, f"Group {group_id} not found")

    # Remove SCIM mapping
    dal = ScimDAL(db_session)
    mapping = dal.get_group_mapping_by_group_id(gid)
    if mapping:
        dal.delete_group_mapping(mapping.id)

    # Remove member relationships and delete group
    db_session.execute(
        sa_delete(User__UserGroup).where(User__UserGroup.user_group_id == gid)
    )

    db_session.delete(group)
    db_session.commit()

    return Response(status_code=204)
