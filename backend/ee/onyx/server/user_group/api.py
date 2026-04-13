from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ee.onyx.db.persona import update_persona_access
from ee.onyx.db.user_group import add_users_to_user_group
from ee.onyx.db.user_group import delete_user_group as db_delete_user_group
from ee.onyx.db.user_group import fetch_user_group
from ee.onyx.db.user_group import fetch_user_groups
from ee.onyx.db.user_group import fetch_user_groups_for_user
from ee.onyx.db.user_group import insert_user_group
from ee.onyx.db.user_group import prepare_user_group_for_deletion
from ee.onyx.db.user_group import rename_user_group
from ee.onyx.db.user_group import set_group_permission__no_commit
from ee.onyx.db.user_group import update_user_curator_relationship
from ee.onyx.db.user_group import update_user_group
from ee.onyx.server.user_group.models import AddUsersToUserGroupRequest
from ee.onyx.server.user_group.models import MinimalUserGroupSnapshot
from ee.onyx.server.user_group.models import SetCuratorRequest
from ee.onyx.server.user_group.models import SetPermissionRequest
from ee.onyx.server.user_group.models import SetPermissionResponse
from ee.onyx.server.user_group.models import UpdateGroupAgentsRequest
from ee.onyx.server.user_group.models import UserGroup
from ee.onyx.server.user_group.models import UserGroupCreate
from ee.onyx.server.user_group.models import UserGroupRename
from ee.onyx.server.user_group.models import UserGroupUpdate
from onyx.auth.permissions import NON_TOGGLEABLE_PERMISSIONS
from onyx.auth.permissions import require_permission
from onyx.auth.users import current_curator_or_admin_user
from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.db.models import UserRole
from onyx.db.persona import get_persona_by_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/manage", tags=PUBLIC_API_TAGS)


@router.get("/admin/user-group")
def list_user_groups(
    include_default: bool = False,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> list[UserGroup]:
    if user.role == UserRole.ADMIN:
        user_groups = fetch_user_groups(
            db_session,
            only_up_to_date=False,
            eager_load_for_snapshot=True,
            include_default=include_default,
        )
    else:
        user_groups = fetch_user_groups_for_user(
            db_session=db_session,
            user_id=user.id,
            only_curator_groups=user.role == UserRole.CURATOR,
            eager_load_for_snapshot=True,
            include_default=include_default,
        )
    return [UserGroup.from_model(user_group) for user_group in user_groups]


@router.get("/user-groups/minimal")
def list_minimal_user_groups(
    include_default: bool = False,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[MinimalUserGroupSnapshot]:
    if user.role == UserRole.ADMIN:
        user_groups = fetch_user_groups(
            db_session,
            only_up_to_date=False,
            include_default=include_default,
        )
    else:
        user_groups = fetch_user_groups_for_user(
            db_session=db_session,
            user_id=user.id,
            include_default=include_default,
        )
    return [
        MinimalUserGroupSnapshot.from_model(user_group) for user_group in user_groups
    ]


@router.get("/admin/user-group/{user_group_id}/permissions")
def get_user_group_permissions(
    user_group_id: int,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[Permission]:
    group = fetch_user_group(db_session, user_group_id)
    if group is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "User group not found")
    return [
        grant.permission for grant in group.permission_grants if not grant.is_deleted
    ]


@router.put("/admin/user-group/{user_group_id}/permissions")
def set_user_group_permission(
    user_group_id: int,
    request: SetPermissionRequest,
    user: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SetPermissionResponse:
    group = fetch_user_group(db_session, user_group_id)
    if group is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "User group not found")

    if request.permission in NON_TOGGLEABLE_PERMISSIONS:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Permission '{request.permission}' cannot be toggled via this endpoint",
        )

    set_group_permission__no_commit(
        group_id=user_group_id,
        permission=request.permission,
        enabled=request.enabled,
        granted_by=user.id,
        db_session=db_session,
    )
    db_session.commit()

    return SetPermissionResponse(permission=request.permission, enabled=request.enabled)


@router.post("/admin/user-group")
def create_user_group(
    user_group: UserGroupCreate,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> UserGroup:
    try:
        db_user_group = insert_user_group(db_session, user_group)
    except IntegrityError:
        raise HTTPException(
            400,
            f"User group with name '{user_group.name}' already exists. Please "
            + "choose a different name.",
        )
    return UserGroup.from_model(db_user_group)


@router.patch("/admin/user-group/rename")
def rename_user_group_endpoint(
    rename_request: UserGroupRename,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> UserGroup:
    group = fetch_user_group(db_session, rename_request.id)
    if group and group.is_default:
        raise OnyxError(OnyxErrorCode.CONFLICT, "Cannot rename a default system group.")
    try:
        return UserGroup.from_model(
            rename_user_group(
                db_session=db_session,
                user_group_id=rename_request.id,
                new_name=rename_request.name,
            )
        )
    except IntegrityError:
        raise OnyxError(
            OnyxErrorCode.DUPLICATE_RESOURCE,
            f"User group with name '{rename_request.name}' already exists.",
        )
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise OnyxError(OnyxErrorCode.NOT_FOUND, msg)
        raise OnyxError(OnyxErrorCode.CONFLICT, msg)


@router.patch("/admin/user-group/{user_group_id}")
def patch_user_group(
    user_group_id: int,
    user_group_update: UserGroupUpdate,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> UserGroup:
    try:
        return UserGroup.from_model(
            update_user_group(
                db_session=db_session,
                user=user,
                user_group_id=user_group_id,
                user_group_update=user_group_update,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/admin/user-group/{user_group_id}/add-users")
def add_users(
    user_group_id: int,
    add_users_request: AddUsersToUserGroupRequest,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> UserGroup:
    try:
        return UserGroup.from_model(
            add_users_to_user_group(
                db_session=db_session,
                user=user,
                user_group_id=user_group_id,
                user_ids=add_users_request.user_ids,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/admin/user-group/{user_group_id}/set-curator")
def set_user_curator(
    user_group_id: int,
    set_curator_request: SetCuratorRequest,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    try:
        update_user_curator_relationship(
            db_session=db_session,
            user_group_id=user_group_id,
            set_curator_request=set_curator_request,
            user_making_change=user,
        )
    except ValueError as e:
        logger.error(f"Error setting user curator: {e}")
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/admin/user-group/{user_group_id}")
def delete_user_group(
    user_group_id: int,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    group = fetch_user_group(db_session, user_group_id)
    if group and group.is_default:
        raise OnyxError(OnyxErrorCode.CONFLICT, "Cannot delete a default system group.")
    try:
        prepare_user_group_for_deletion(db_session, user_group_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if DISABLE_VECTOR_DB:
        user_group = fetch_user_group(db_session, user_group_id)
        if user_group:
            db_delete_user_group(db_session, user_group)


@router.patch("/admin/user-group/{user_group_id}/agents")
def update_group_agents(
    user_group_id: int,
    request: UpdateGroupAgentsRequest,
    user: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    for agent_id in request.added_agent_ids:
        persona = get_persona_by_id(
            persona_id=agent_id, user=user, db_session=db_session
        )
        current_group_ids = [g.id for g in persona.groups]
        if user_group_id not in current_group_ids:
            update_persona_access(
                persona_id=agent_id,
                creator_user_id=user.id,
                db_session=db_session,
                group_ids=current_group_ids + [user_group_id],
            )

    for agent_id in request.removed_agent_ids:
        persona = get_persona_by_id(
            persona_id=agent_id, user=user, db_session=db_session
        )
        current_group_ids = [g.id for g in persona.groups]
        update_persona_access(
            persona_id=agent_id,
            creator_user_id=user.id,
            db_session=db_session,
            group_ids=[gid for gid in current_group_ids if gid != user_group_id],
        )

    db_session.commit()
