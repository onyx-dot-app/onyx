from collections.abc import Collection, Mapping
from dataclasses import dataclass, field, replace
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission
from onyx.auth.scoped_permissions import assert_within_scope
from onyx.db.enums import Permission, SkillInstallationPolicy, SkillSharePermission
from onyx.db.models import User
from onyx.db.users import lock_group_membership
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


@dataclass(frozen=True)
class ResourceAccessChange:
    public_permission: SkillSharePermission | None = None
    set_public_permission: bool = False
    installation_policy: SkillInstallationPolicy | None = None
    user_shares: Mapping[UUID, SkillSharePermission] | None = None
    group_shares: Mapping[int, SkillSharePermission] | None = None


@dataclass(frozen=True)
class ResourceAccessState:
    owner_user_id: UUID | None
    # No active owner: only global managers change direct-user grants.
    ownership_vacant: bool
    public_permission: SkillSharePermission | None
    user_shares: Mapping[UUID, SkillSharePermission]
    group_shares: Mapping[int, SkillSharePermission]


@dataclass
class AccessMutationResult:
    succeeded: list[UUID] = field(default_factory=list)
    failed: dict[UUID, str] = field(default_factory=dict)
    affected: set[UUID] = field(default_factory=set)


class ResourceAccessAdapter[Resource](Protocol):
    permission: Permission

    def load(self, resource_id: UUID, user: User, db_session: Session) -> Resource: ...
    def state(self, resource: Resource) -> ResourceAccessState: ...
    def write(
        self, resource: Resource, change: ResourceAccessChange, db_session: Session
    ) -> None: ...
    def affected_users(
        self, resource_ids: Collection[UUID], db_session: Session
    ) -> dict[UUID, set[UUID]]: ...


def mutate_resource_access[Resource](
    resource_ids: Collection[UUID],
    change: ResourceAccessChange,
    user: User,
    db_session: Session,
    adapter: ResourceAccessAdapter[Resource],
    *,
    add_only: bool = False,
    allow_partial: bool = False,
) -> AccessMutationResult:
    """Caller commits, then pushes result.affected once for the whole batch."""
    lock_group_membership(db_session)
    result = AccessMutationResult()
    resources: dict[UUID, Resource] = {}
    for resource_id in sorted(set(resource_ids)):
        try:
            with db_session.begin_nested():
                resources[resource_id] = adapter.load(resource_id, user, db_session)
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
                    )
                    or change.installation_policy is not None
                ) and not has_global_permission(user, adapter.permission):
                    raise OnyxError(
                        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                        "Company access changes require global manage-skills permission.",
                    )
                groups = change.group_shares
                if groups is not None and add_only:
                    groups = dict(current.group_shares) | dict(groups)
                if groups is not None and groups != current.group_shares:
                    assert_within_scope(
                        user,
                        db_session,
                        permission=adapter.permission,
                        current_group_ids=list(current.group_shares),
                        requested_group_ids=list(groups),
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
                    and current.ownership_vacant
                    and not has_global_permission(user, adapter.permission)
                ):
                    raise OnyxError(
                        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                        "Company user grants require global manage-skills permission.",
                    )
                adapter.write(
                    resource,
                    replace(change, user_shares=users, group_shares=groups),
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
