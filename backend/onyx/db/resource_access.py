from collections.abc import Collection, Mapping
from dataclasses import dataclass, field, replace
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission
from onyx.auth.scoped_permissions import assert_within_scope
from onyx.db.enums import (
    Permission,
    SkillInstallationPolicy,
    SkillSharePermission,
)
from onyx.db.models import User
from onyx.db.users import fetch_user_by_id, lock_group_membership
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


@dataclass(frozen=True)
class ResourceAccessChange:
    public_permission: SkillSharePermission | None = None
    set_public_permission: bool = False
    installation_policy: SkillInstallationPolicy | None = None
    user_shares: Mapping[UUID, SkillSharePermission] | None = None
    group_shares: Mapping[int, SkillSharePermission] | None = None
    group_installation_policies: Mapping[int, SkillInstallationPolicy | None] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class ResourceAccessState:
    owner_user_id: UUID | None
    public_permission: SkillSharePermission | None
    user_shares: Mapping[UUID, SkillSharePermission]
    group_shares: Mapping[int, SkillSharePermission]
    group_installation_policies: Mapping[int, SkillInstallationPolicy | None]
    sharing_owner_id: UUID | None = None


@dataclass
class AccessMutationResult:
    succeeded: list[UUID] = field(default_factory=list)
    failed: dict[UUID, str] = field(default_factory=dict)
    affected: set[UUID] = field(default_factory=set)


class ResourceAccessAdapter[Resource](Protocol):
    permission: Permission

    def load(
        self,
        resource_id: UUID,
        user: User,
        db_session: Session,
        *,
        allow_management: bool,
    ) -> Resource: ...
    def state(self, resource: Resource) -> ResourceAccessState: ...
    def write(
        self, resource: Resource, change: ResourceAccessChange, db_session: Session
    ) -> None: ...
    def affected_users(
        self, resource_ids: Collection[UUID], db_session: Session
    ) -> dict[UUID, set[UUID]]: ...


def lock_resource_access_user(user_id: UUID, db_session: Session) -> User:
    """Reload authority after membership writers finish, using the request session."""
    lock_group_membership(db_session)
    return fetch_resource_access_user(user_id, db_session)


def fetch_resource_access_user(user_id: UUID, db_session: Session) -> User:
    """Refresh read authority without serializing reads against workspace writes."""
    user = fetch_user_by_id(db_session, user_id, refresh=True)
    if (
        user is None
        or not user.is_active
        or not has_global_permission(user, Permission.BASIC_ACCESS)
    ):
        raise OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS)
    return user


def mutate_resource_access[Resource](
    resource_ids: Collection[UUID],
    change: ResourceAccessChange,
    user: User,
    db_session: Session,
    adapter: ResourceAccessAdapter[Resource],
    *,
    add_only: bool = False,
    allow_partial: bool = False,
    allow_management: bool = True,
) -> AccessMutationResult:
    """Caller commits, then pushes result.affected once for the whole batch."""
    user = lock_resource_access_user(user.id, db_session)
    result = AccessMutationResult()
    resources: dict[UUID, Resource] = {}
    for resource_id in sorted(set(resource_ids)):
        try:
            with db_session.begin_nested():
                resources[resource_id] = adapter.load(
                    resource_id, user, db_session, allow_management=allow_management
                )
        except OnyxError as exc:
            if not allow_partial:
                raise
            result.failed[resource_id] = exc.detail
    before = adapter.affected_users(resources.keys(), db_session)
    for resource_id, resource in resources.items():
        try:
            with db_session.begin_nested():
                current = adapter.state(resource)
                if (
                    (
                        change.set_public_permission
                        and change.public_permission != current.public_permission
                        and current.sharing_owner_id != user.id
                    )
                    or change.installation_policy is not None
                ) and not (
                    allow_management and has_global_permission(user, adapter.permission)
                ):
                    raise OnyxError(
                        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                        "Company access changes require global manage-skills permission.",
                    )
                groups = change.group_shares
                if groups is not None and add_only:
                    groups = dict(current.group_shares) | dict(groups)
                policies = dict(current.group_installation_policies)
                policies.update(change.group_installation_policies)
                retained_groups = groups if groups is not None else current.group_shares
                policies = {
                    key: value
                    for key, value in policies.items()
                    if key in retained_groups
                }
                if (
                    change.group_installation_policies.keys()
                    - (groups if groups is not None else current.group_shares).keys()
                ):
                    raise OnyxError(
                        OnyxErrorCode.INVALID_INPUT,
                        "A group installation setting requires a group share.",
                    )
                if (
                    groups is not None and groups != current.group_shares
                ) or change.group_installation_policies:
                    owner_grant = (
                        current.sharing_owner_id == user.id
                        and all(
                            current.group_installation_policies.get(group_id) == policy
                            for group_id, policy in change.group_installation_policies.items()
                        )
                        and all(
                            policy is None or group_id in retained_groups
                            for group_id, policy in current.group_installation_policies.items()
                        )
                    )
                    if not owner_grant:
                        if not allow_management:
                            raise OnyxError(
                                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                                f"API token lacks {adapter.permission.value} scope.",
                            )
                        assert_within_scope(
                            user,
                            db_session,
                            permission=adapter.permission,
                            current_group_ids=list(current.group_shares),
                            requested_group_ids=list(
                                groups if groups is not None else current.group_shares
                            ),
                            is_non_public=current.public_permission is None
                            and (
                                not change.set_public_permission
                                or change.public_permission is None
                            ),
                        )
                users = change.user_shares
                if users is not None:
                    users = dict(users)
                    if add_only:
                        users = dict(current.user_shares) | users
                    if current.owner_user_id is not None:
                        users.pop(current.owner_user_id, None)
                if (
                    users is not None
                    and users != current.user_shares
                    and current.owner_user_id is None
                    and not (
                        allow_management
                        and has_global_permission(user, adapter.permission)
                    )
                ):
                    raise OnyxError(
                        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                        "Company user grants require global manage-skills permission.",
                    )
                if (
                    current.sharing_owner_id is not None
                    and current.sharing_owner_id != user.id
                    and (
                        (
                            change.set_public_permission
                            and change.public_permission != current.public_permission
                        )
                        or (users is not None and users != current.user_shares)
                        or (groups is not None and groups != current.group_shares)
                    )
                ):
                    raise OnyxError(
                        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                        "Only the owner can share personal synced skills.",
                    )
                adapter.write(
                    resource,
                    replace(
                        change,
                        user_shares=users,
                        group_shares=(
                            groups
                            if groups is not None
                            else current.group_shares
                            if change.group_installation_policies
                            else None
                        ),
                        group_installation_policies=policies,
                    ),
                    db_session,
                )
                db_session.flush()
            result.succeeded.append(resource_id)
        except OnyxError as exc:
            if not allow_partial:
                raise
            result.failed[resource_id] = exc.detail
    after = adapter.affected_users(result.succeeded, db_session)
    for resource_id in result.succeeded:
        result.affected.update(before.get(resource_id, set()))
        result.affected.update(after.get(resource_id, set()))
    return result
