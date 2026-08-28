from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ee.onyx.db.document_set import set_document_set_group_membership__no_commit
from ee.onyx.db.persona import update_persona_access
from ee.onyx.db.user_group import (
    add_users_to_user_group,
    assert_group_membership_survives_deletion,
    fetch_user_group,
    fetch_user_group_for_snapshot,
    fetch_user_groups,
    fetch_user_groups_for_user,
    insert_user_group,
    make_group_manager,
    prepare_user_group_for_deletion,
    rename_user_group,
    revoke_group_manager,
    set_group_permissions_bulk__no_commit,
    set_user_group_incognito,
    update_user_group,
)
from ee.onyx.db.user_group import delete_user_group as db_delete_user_group
from ee.onyx.server.user_group.models import (
    AddUsersToUserGroupRequest,
    BulkSetPermissionsRequest,
    MinimalUserGroupSnapshot,
    SetGroupManagerRequest,
    UpdateGroupAgentsRequest,
    UpdateGroupDocumentSetsRequest,
    UserGroup,
    UserGroupCreate,
    UserGroupIncognitoUpdate,
    UserGroupRename,
    UserGroupUpdate,
)
from onyx.auth.permission_projection import user_group_permissions
from onyx.auth.permissions import (
    NON_TOGGLEABLE_PERMISSIONS,
    PERMISSION_REGISTRY,
    PermissionRegistryEntry,
    get_effective_permissions,
    has_global_permission,
    has_permission,
    require_permission,
)
from onyx.auth.scoped_permissions import (
    assert_manages_group,
    assert_within_scope,
    get_scoped_groups,
    manages_group,
)
from onyx.background.celery.tasks.beat_schedule import BEAT_EXPIRES_DEFAULT
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.configs.constants import PUBLIC_API_TAGS, OnyxCeleryPriority, OnyxCeleryTask
from onyx.db.document_set import (
    get_document_sets_by_ids,
    get_group_ids_for_document_sets,
)
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission, PermissionAuthority
from onyx.db.models import User
from onyx.db.persona import fetch_persona_by_id_for_user, get_personas_by_ids
from onyx.db.user_group import assert_group_config_is_editable
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.security.store import get_security_settings
from onyx.utils.audit import (
    AuditAction,
    AuditOutcome,
    actor_from_user,
    emit_audit_event,
)
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/manage", tags=PUBLIC_API_TAGS)


@router.get("/admin/user-group")
def list_user_groups(
    include_default: bool = False,
    user: User = Depends(
        require_permission(Permission.READ_USER_GROUPS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> list[UserGroup]:
    # GATE 2 (read): the group list has no membership filter, so a scoped manager must be
    # restricted here or they'd see the whole org. Only their set is consulted — a global
    # holder short-circuits in manages_group — but fall back to an empty set, never None,
    # or manages_group re-queries once per group.
    managed_group_ids = (
        get_scoped_groups(user, db_session, Permission.MANAGE_USER_GROUPS)
        if has_permission(user, Permission.MANAGE_USER_GROUPS)
        is PermissionAuthority.SCOPED
        else set[int]()
    )
    is_user_groups_admin = has_global_permission(user, Permission.MANAGE_USER_GROUPS)
    is_full_admin = has_global_permission(user, Permission.FULL_ADMIN_PANEL_ACCESS)
    restrict_to_group_ids = (
        None
        if has_global_permission(user, Permission.READ_USER_GROUPS)
        else managed_group_ids
    )
    user_groups = fetch_user_groups(
        db_session,
        only_up_to_date=False,
        eager_load_for_snapshot=True,
        include_default=include_default,
        restrict_to_group_ids=restrict_to_group_ids,
    )
    mask_credential_prefix = get_security_settings().mask_credential_prefix
    return [
        UserGroup.from_model(
            user_group,
            mask_credential_prefix=mask_credential_prefix,
            permissions=user_group_permissions(
                can_manage=manages_group(
                    user,
                    db_session,
                    group_id=user_group.id,
                    managed_group_ids=managed_group_ids,
                ),
                is_user_groups_admin=is_user_groups_admin,
                is_full_admin=is_full_admin,
                is_default=user_group.is_default,
            ),
        )
        for user_group in user_groups
    ]


@router.get("/admin/user-group/{user_group_id}")
def get_user_group(
    user_group_id: int,
    user: User = Depends(
        require_permission(Permission.READ_USER_GROUPS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> UserGroup:
    """Read one group. The listing carries every group with its nested connector,
    document-set and agent snapshots, so reading one used to cost all of them."""
    # GATE 2 (read): mirrors list_user_groups — a scoped manager may only read a
    # group they manage, so they cannot enumerate the org one id at a time.
    managed_group_ids = (
        get_scoped_groups(user, db_session, Permission.MANAGE_USER_GROUPS)
        if has_permission(user, Permission.MANAGE_USER_GROUPS)
        is PermissionAuthority.SCOPED
        else set[int]()
    )
    can_manage = manages_group(
        user, db_session, group_id=user_group_id, managed_group_ids=managed_group_ids
    )
    if not has_global_permission(user, Permission.READ_USER_GROUPS) and not can_manage:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "User group not found")

    user_group = fetch_user_group_for_snapshot(db_session, user_group_id)
    if user_group is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "User group not found")

    return UserGroup.from_model(
        user_group,
        mask_credential_prefix=get_security_settings().mask_credential_prefix,
        permissions=user_group_permissions(
            can_manage=can_manage,
            is_user_groups_admin=has_global_permission(
                user, Permission.MANAGE_USER_GROUPS
            ),
            is_full_admin=has_global_permission(
                user, Permission.FULL_ADMIN_PANEL_ACCESS
            ),
            is_default=user_group.is_default,
        ),
    )


@router.get("/user-groups/minimal")
def list_minimal_user_groups(
    include_default: bool = False,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[MinimalUserGroupSnapshot]:
    if Permission.FULL_ADMIN_PANEL_ACCESS in get_effective_permissions(user):
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


@router.get("/admin/permissions/registry")
def get_permission_registry(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> list[PermissionRegistryEntry]:
    return PERMISSION_REGISTRY


@router.get("/admin/user-group/{user_group_id}/permissions")
def get_user_group_permissions(
    user_group_id: int,
    include_non_toggleable: bool = False,
    _: User = Depends(require_permission(Permission.MANAGE_USER_GROUPS)),
    db_session: Session = Depends(get_session),
) -> list[Permission]:
    group = fetch_user_group(db_session, user_group_id)
    if group is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "User group not found")
    return [
        grant.permission
        for grant in group.permission_grants
        if not grant.is_deleted
        and (
            include_non_toggleable or grant.permission not in NON_TOGGLEABLE_PERMISSIONS
        )
    ]


@router.put("/admin/user-group/{user_group_id}/permissions")
def set_user_group_permissions(
    user_group_id: int,
    request: BulkSetPermissionsRequest,
    user: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[Permission]:
    group = fetch_user_group(db_session, user_group_id)
    if group is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "User group not found")
    assert_group_config_is_editable(
        db_session, user_group_id, "change the permissions of"
    )

    non_toggleable = [p for p in request.permissions if p in NON_TOGGLEABLE_PERMISSIONS]
    if non_toggleable:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Permissions {non_toggleable} cannot be toggled via this endpoint",
        )

    group_name = group.name

    change = set_group_permissions_bulk__no_commit(
        group_id=user_group_id,
        desired_permissions=set(request.permissions),
        granted_by=user.id,
        db_session=db_session,
    )
    db_session.commit()

    emit_audit_event(
        AuditAction.USER_GROUP_PERMISSION_CHANGE,
        AuditOutcome.SUCCESS,
        actor=actor_from_user(user),
        resource_type="user_group",
        resource_id=user_group_id,
        extra={
            "group_name": group_name,
            "added": [permission.value for permission in change.added],
            "removed": [permission.value for permission in change.removed],
        },
    )

    return change.enabled


@router.post("/admin/user-group")
def create_user_group(
    user_group: UserGroupCreate,
    user: User = Depends(require_permission(Permission.MANAGE_USER_GROUPS)),
    db_session: Session = Depends(get_session),
) -> UserGroup:
    try:
        db_user_group = insert_user_group(db_session, user_group)
    except IntegrityError:
        raise OnyxError(
            OnyxErrorCode.DUPLICATE_RESOURCE,
            f"User group with name '{user_group.name}' already exists. Please "
            "choose a different name.",
        )

    emit_audit_event(
        AuditAction.USER_GROUP_CREATE,
        AuditOutcome.SUCCESS,
        actor=actor_from_user(user),
        resource_type="user_group",
        resource_id=db_user_group.id,
        extra={
            "name": user_group.name,
            "user_ids": [str(uid) for uid in user_group.user_ids],
            "cc_pair_ids": list(user_group.cc_pair_ids),
        },
    )

    return UserGroup.from_model(
        db_user_group,
        mask_credential_prefix=get_security_settings().mask_credential_prefix,
    )


@router.patch("/admin/user-group/rename")
def rename_user_group_endpoint(
    rename_request: UserGroupRename,
    user: User = Depends(
        require_permission(Permission.MANAGE_USER_GROUPS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> UserGroup:
    # GATE 2: rename's DB fn takes no user and re-reads nothing, so gate here.
    assert_manages_group(user, db_session, group_id=rename_request.id)
    assert_group_config_is_editable(db_session, rename_request.id, "rename")

    existing = fetch_user_group(db_session, rename_request.id)
    previous_name = existing.name if existing else None

    try:
        renamed = rename_user_group(
            db_session=db_session,
            user_group_id=rename_request.id,
            new_name=rename_request.name,
        )
        emit_audit_event(
            AuditAction.USER_GROUP_RENAME,
            AuditOutcome.SUCCESS,
            actor=actor_from_user(user),
            resource_type="user_group",
            resource_id=rename_request.id,
            extra={"previous_name": previous_name, "new_name": rename_request.name},
        )
        return UserGroup.from_model(
            renamed,
            mask_credential_prefix=get_security_settings().mask_credential_prefix,
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


@router.patch("/admin/user-group/{user_group_id}/incognito")
def patch_user_group_incognito(
    user_group_id: int,
    update: UserGroupIncognitoUpdate,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> UserGroup:
    """Only meaningful while the security setting is groups-only, but always
    storable so admins can stage membership before flipping the mode."""
    assert_group_config_is_editable(
        db_session, user_group_id, "change incognito access on"
    )
    try:
        return UserGroup.from_model(
            set_user_group_incognito(
                db_session=db_session,
                user_group_id=user_group_id,
                enabled=update.enabled,
            ),
            mask_credential_prefix=get_security_settings().mask_credential_prefix,
        )
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, str(e))


@router.patch("/admin/user-group/{user_group_id}")
def patch_user_group(
    user_group_id: int,
    user_group_update: UserGroupUpdate,
    user: User = Depends(
        require_permission(Permission.MANAGE_USER_GROUPS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> UserGroup:
    try:
        return UserGroup.from_model(
            update_user_group(
                db_session=db_session,
                user=user,
                user_group_id=user_group_id,
                user_group_update=user_group_update,
            ),
            mask_credential_prefix=get_security_settings().mask_credential_prefix,
        )
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, str(e))


@router.post("/admin/user-group/{user_group_id}/add-users")
def add_users(
    user_group_id: int,
    add_users_request: AddUsersToUserGroupRequest,
    user: User = Depends(
        require_permission(Permission.MANAGE_USER_GROUPS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> UserGroup:
    try:
        return UserGroup.from_model(
            add_users_to_user_group(
                db_session=db_session,
                user=user,
                user_group_id=user_group_id,
                user_ids=add_users_request.user_ids,
            ),
            mask_credential_prefix=get_security_settings().mask_credential_prefix,
        )
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, str(e))


@router.delete("/admin/user-group/{user_group_id}")
def delete_user_group(
    user_group_id: int,
    user: User = Depends(require_permission(Permission.MANAGE_USER_GROUPS)),
    db_session: Session = Depends(get_session),
) -> None:
    assert_group_config_is_editable(db_session, user_group_id, "delete")
    assert_group_membership_survives_deletion(db_session, user_group_id)

    # Deletion drops every membership, so capture the roster before it runs.
    existing = fetch_user_group(db_session, user_group_id)
    group_name = existing.name if existing else None
    member_ids = [str(member.id) for member in existing.users] if existing else []

    try:
        prepare_user_group_for_deletion(db_session, user_group_id)
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, str(e))

    emit_audit_event(
        AuditAction.USER_GROUP_DELETE,
        AuditOutcome.SUCCESS,
        actor=actor_from_user(user),
        resource_type="user_group",
        resource_id=user_group_id,
        extra={
            "name": group_name,
            "member_ids": member_ids,
            "member_count": len(member_ids),
        },
    )

    if DISABLE_VECTOR_DB:
        user_group = fetch_user_group(db_session, user_group_id)
        if user_group:
            db_delete_user_group(db_session, user_group)


@router.patch("/admin/user-group/{user_group_id}/agents")
def update_group_agents(
    user_group_id: int,
    request: UpdateGroupAgentsRequest,
    user: User = Depends(
        require_permission(Permission.MANAGE_USER_GROUPS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> None:
    # GATE 2: fetch_persona_by_id_for_user scopes the agent but says nothing about
    # the group, so without this a manager of one group could attach agents into
    # any other. Mirrors rename_user_group_endpoint and set_group_manager.
    assert_manages_group(user, db_session, group_id=user_group_id)

    if fetch_user_group(db_session, user_group_id) is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "User group not found")
    assert_group_config_is_editable(db_session, user_group_id, "share agents with")

    attach_ids = set(request.added_agent_ids)
    detach_ids = set(request.removed_agent_ids)
    if attach_ids & detach_ids:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "An agent cannot be both added and removed.",
        )

    # Read groups under the lock: update_persona_access replaces the whole group list,
    # so a pre-lock read re-applies a share a concurrent save just revoked.
    get_personas_by_ids(list(attach_ids | detach_ids), db_session, for_update=True)

    # A global groups admin shares any agent (READ_AGENTS resolves the whole org on the
    # non-editable branch); a scoped manager stays pinned to their editable set.
    get_editable = not has_global_permission(user, Permission.MANAGE_USER_GROUPS)

    for agent_id in attach_ids:
        persona = fetch_persona_by_id_for_user(
            db_session=db_session,
            persona_id=agent_id,
            user=user,
            get_editable=get_editable,
        )
        current_group_ids = [g.id for g in persona.groups]
        if user_group_id not in current_group_ids:
            update_persona_access(
                persona_id=agent_id,
                creator_user_id=user.id,
                db_session=db_session,
                acting_user=user,
                group_ids=current_group_ids + [user_group_id],
            )

    for agent_id in detach_ids:
        persona = fetch_persona_by_id_for_user(
            db_session=db_session,
            persona_id=agent_id,
            user=user,
            get_editable=get_editable,
        )
        current_group_ids = [g.id for g in persona.groups]
        update_persona_access(
            persona_id=agent_id,
            creator_user_id=user.id,
            db_session=db_session,
            acting_user=user,
            group_ids=[gid for gid in current_group_ids if gid != user_group_id],
        )

    db_session.commit()


@router.patch("/admin/user-group/{user_group_id}/document-sets")
def update_group_document_sets(
    user_group_id: int,
    request: UpdateGroupDocumentSetsRequest,
    user: User = Depends(
        require_permission(Permission.MANAGE_USER_GROUPS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
    tenant_id: str = Depends(get_current_tenant_id),
) -> None:
    """Share document sets with a group from the group's side — the document-set route is
    gated on MANAGE_DOCUMENT_SETS, which a groups admin doesn't hold."""
    # GATE 2: the group must be one the caller administers.
    assert_manages_group(user, db_session, group_id=user_group_id)

    if fetch_user_group(db_session, user_group_id) is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "User group not found")
    assert_group_config_is_editable(
        db_session, user_group_id, "share document sets with"
    )

    attach_ids = set(request.added_document_set_ids)
    detach_ids = set(request.removed_document_set_ids)
    if attach_ids & detach_ids:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "A document set cannot be both added and removed.",
        )
    if not attach_ids and not detach_ids:
        return

    document_sets = {
        document_set.id: document_set
        for document_set in get_document_sets_by_ids(
            db_session, list(attach_ids | detach_ids), for_update=True
        )
    }
    missing = sorted((attach_ids | detach_ids) - document_sets.keys())
    if missing:
        raise OnyxError(
            OnyxErrorCode.DOCUMENT_SET_NOT_FOUND,
            f"Document set(s) {missing} do not exist",
        )

    # A global groups admin shares any set; a scoped manager is held to private sets
    # inside their managed groups.
    if not has_global_permission(user, Permission.MANAGE_USER_GROUPS):
        groups_by_document_set = get_group_ids_for_document_sets(
            db_session, list(document_sets)
        )
        for document_set_id, document_set in document_sets.items():
            current_group_ids = groups_by_document_set[document_set_id]
            requested_group_ids = (
                current_group_ids | {user_group_id}
                if document_set_id in attach_ids
                else current_group_ids - {user_group_id}
            )
            assert_within_scope(
                user,
                db_session,
                permission=Permission.MANAGE_DOCUMENT_SETS,
                current_group_ids=current_group_ids,
                requested_group_ids=requested_group_ids,
                is_non_public=not document_set.is_public,
            )

    try:
        changed = set_document_set_group_membership__no_commit(
            db_session=db_session,
            user_group_id=user_group_id,
            to_attach=[document_sets[ds_id] for ds_id in attach_ids],
            to_detach=[document_sets[ds_id] for ds_id in detach_ids],
        )
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e))

    db_session.commit()

    if changed and not DISABLE_VECTOR_DB:
        client_app.send_task(
            OnyxCeleryTask.CHECK_FOR_VESPA_SYNC_TASK,
            kwargs={"tenant_id": tenant_id},
            priority=OnyxCeleryPriority.HIGH,
            expires=BEAT_EXPIRES_DEFAULT,
        )


@router.put("/admin/user-group/{user_group_id}/manager")
def set_group_manager(
    user_group_id: int,
    request: SetGroupManagerRequest,
    user: User = Depends(
        require_permission(Permission.MANAGE_USER_GROUPS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> None:
    # GATE 2: an admin / global MANAGE_USER_GROUPS holder may assign in any group;
    # a scoped manager may only (de)assign managers within a group they manage — so
    # a manager can delegate within their own group but not beyond it.
    assert_manages_group(user, db_session, group_id=user_group_id)
    assert_group_config_is_editable(db_session, user_group_id, "assign a manager on")

    group = fetch_user_group(db_session, user_group_id)
    target = (
        next((member for member in group.users if member.id == request.user_id), None)
        if group
        else None
    )

    try:
        if request.is_manager:
            make_group_manager(db_session, request.user_id, user_group_id)
        else:
            revoke_group_manager(db_session, request.user_id, user_group_id)
    except ValueError as e:
        # Target isn't a member of the group (a manager is always a member).
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e))
    db_session.commit()

    emit_audit_event(
        AuditAction.USER_GROUP_MANAGER_CHANGE,
        AuditOutcome.SUCCESS,
        actor=actor_from_user(user),
        resource_type="user_group",
        resource_id=user_group_id,
        extra={
            "group_name": group.name if group else None,
            "target_user_id": str(request.user_id),
            "target_email": target.email if target else None,
            "is_manager": request.is_manager,
        },
    )
