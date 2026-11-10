"""DB operations for skill rows.

Management authorization:
- `VIEW` includes associated custom rows but excludes associated built-in
  provider rows, applies normal ownership and sharing visibility, and lets
  admins view all remaining skills.
- `EDIT` is the skill mutation policy. It excludes built-in rows and only
  returns custom rows the user can modify.

Runtime selection is deliberately separate from authorization. It applies
visibility without an admin bypass, user enablement for custom skills, app
readiness for associated skills, validity, and built-in availability.

Delete is a hard delete: `delete_skill` removes the row and its versions and
returns their bundle file ids. Callers delete those files after commit with
`delete_unreferenced_skill_bundles`; the orphan cleanup task retries failures.

Mutation helpers do not commit unless their docstring explicitly says otherwise.
Callers normally control the transaction boundary so multi-step operations can
roll back atomically.
"""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Literal
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Select,
    and_,
    delete,
    exists,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, contains_eager, selectinload

from onyx.auth.permissions import has_global_permission, has_permission
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    Permission,
    PermissionAuthority,
    SandboxStatus,
    SkillInstallationPolicy,
    SkillSharePermission,
)
from onyx.db.external_app import (
    SkillExternalAppDependencyState,
    get_skill_external_app_dependencies,
)
from onyx.db.models import (
    ExternalApp__Skill,
    Sandbox,
    Skill,
    Skill__User,
    Skill__UserGroup,
    SkillVersion,
    User,
    User__UserGroup,
    UserSkillPreference,
)
from onyx.db.resource_access import (
    ResourceAccessAdapter,
    ResourceAccessState,
    mutate_resource_access,
)
from onyx.db.resource_access import (
    ResourceAccessChange as SkillSharingChange,
)
from onyx.db.scoped_permissions import (
    scoped_group_ids_subquery,
    within_managed_scope_clause,
)
from onyx.db.skill_version import (
    persist_skill_version_validity,
    save_skill_version,
    skill_bundle_file_ids,
)
from onyx.db.user_group import assert_not_shared_with_default_group
from onyx.db.utils import is_fk_violation, is_unique_violation
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.ingest import IngestedBundle


class SkillManagementPolicy(str, Enum):
    VIEW = "view"
    EDIT = "edit"


@dataclass(frozen=True)
class SkillValidityUpdate:
    skill_id: UUID
    version_id: UUID
    bundle_file_id: str | None
    is_valid: bool


@dataclass(frozen=True)
class SkillUserState:
    enabled: bool
    can_toggle: bool
    external_app_dependency: SkillExternalAppDependencyState | None


def _is_shared_with_user(
    user: User,
    permission: SkillSharePermission | None = None,
) -> ColumnElement[bool]:
    stmt = (
        select(Skill__User.skill_id)
        .where(Skill__User.skill_id == Skill.id)
        .where(Skill__User.user_id == user.id)
    )
    if permission is not None:
        stmt = stmt.where(Skill__User.permission == permission)
    return stmt.exists()


def _is_shared_with_user_group(
    user: User,
    permission: SkillSharePermission | None = None,
) -> ColumnElement[bool]:
    stmt = (
        select(Skill__UserGroup.skill_id)
        .join(
            User__UserGroup,
            User__UserGroup.user_group_id == Skill__UserGroup.user_group_id,
        )
        .where(Skill__UserGroup.skill_id == Skill.id)
        .where(User__UserGroup.user_id == user.id)
    )
    if permission is not None:
        stmt = stmt.where(Skill__UserGroup.permission == permission)
    return stmt.exists()


def _is_group_shared_only_within_managed_scope(user: User) -> ColumnElement[bool]:
    """A scoped manager may edit a skill only when every group it is shared with
    is one they manage, and it isn't published org-wide. Delegates to the shared
    read-side helper so this can't drift from the write-side GATE 2."""
    return within_managed_scope_clause(
        resource_id_col=Skill.id,
        junction_resource_col=Skill__UserGroup.skill_id,
        junction_group_col=Skill__UserGroup.user_group_id,
        non_public_clause=Skill.public_permission.is_(None),
        managed_subq=scoped_group_ids_subquery(user),
    )


def _is_owned_custom_skill(user: User) -> ColumnElement[bool]:
    return and_(
        Skill.author_user_id.is_not(None),
        Skill.author_user_id == user.id,
        Skill.built_in_skill_id.is_(None),
    )


def skill_visible_to_user(user: User) -> ColumnElement[bool]:
    return or_(
        Skill.public_permission.isnot(None),
        _is_shared_with_user(user),
        _is_shared_with_user_group(user),
        _is_owned_custom_skill(user),
    )


def _is_editable_by_user(user: User) -> ColumnElement[bool]:
    editable = or_(
        _is_owned_custom_skill(user),
        _is_shared_with_user(user, SkillSharePermission.EDITOR),
        _is_shared_with_user_group(user, SkillSharePermission.EDITOR),
        Skill.public_permission == SkillSharePermission.EDITOR,
    )
    if has_permission(user, Permission.MANAGE_SKILLS) is PermissionAuthority.SCOPED:
        editable = or_(editable, _is_group_shared_only_within_managed_scope(user))
    return editable


def _is_required_for_user(user: User) -> ColumnElement[bool]:
    return and_(
        Skill.installation_policy == SkillInstallationPolicy.REQUIRED,
        skill_visible_to_user(user),
    )


def _is_enabled_for_user(user: User) -> ColumnElement[bool]:
    preference = (
        select(UserSkillPreference.enabled)
        .where(
            UserSkillPreference.user_id == user.id,
            UserSkillPreference.skill_id == Skill.id,
        )
        .correlate(Skill)
        .scalar_subquery()
    )
    selected_name = exists().where(
        UserSkillPreference.user_id == user.id,
        UserSkillPreference.name == Skill.name,
        UserSkillPreference.enabled.is_(True),
        UserSkillPreference.skill_id.in_(
            select(Skill.id).where(skill_visible_to_user(user)).correlate(None)
        ),
    )
    visible = skill_visible_to_user(user)
    required_name = Skill.name.in_(
        select(Skill.name).where(_is_required_for_user(user)).correlate(None)
    )
    return or_(
        Skill.built_in_skill_id.isnot(None),
        _is_required_for_user(user),
        and_(
            ~required_name,
            or_(
                preference.is_(True),
                and_(
                    Skill.installation_policy == SkillInstallationPolicy.DEFAULT,
                    visible,
                    preference.is_(None),
                    ~selected_name,
                ),
            ),
        ),
    )


def _exclude_unavailable_built_in_skills(
    stmt: Select[tuple[Skill]], db_session: Session
) -> Select[tuple[Skill]]:
    """Hide built-ins whose codified ``is_available(db)`` returns False.
    User-facing reads use this; admin reads don't (admins see all rows)."""
    unavailable = [
        d.built_in_skill_id
        for d in BUILT_IN_SKILLS.values()
        if not d.is_available(db_session)
    ]
    if not unavailable:
        return stmt
    return stmt.where(
        or_(
            Skill.built_in_skill_id.is_(None),
            Skill.built_in_skill_id.notin_(unavailable),
        )
    )


def _skill_select_with_eager_load(*, order_by_name: bool) -> Select[tuple[Skill]]:
    stmt = (
        select(Skill)
        .outerjoin(Skill.current_version)
        .options(
            contains_eager(Skill.current_version),
            selectinload(Skill.author),
            selectinload(Skill.user_shares).selectinload(Skill__User.user),
            selectinload(Skill.group_shares).selectinload(Skill__UserGroup.user_group),
        )
    )
    if order_by_name:
        stmt = stmt.order_by(Skill.name, Skill.id)
    return stmt


def _skill_select_for_management_policy(
    *,
    policy: SkillManagementPolicy,
    db_session: Session,
    user: User,
    order_by_name: bool,
) -> Select[tuple[Skill]]:
    stmt = _skill_select_with_eager_load(order_by_name=order_by_name)
    if policy == SkillManagementPolicy.VIEW:
        # Associated custom skills are first-class; provider-owned built-ins
        # remain represented only through the Apps surfaces.
        stmt = stmt.where(
            or_(
                Skill.built_in_skill_id.is_(None),
                ~exists().where(ExternalApp__Skill.skill_id == Skill.id),
            )
        )
        if has_global_permission(user, Permission.MANAGE_SKILLS):
            return stmt
        stmt = stmt.where(skill_visible_to_user(user))
        return _exclude_unavailable_built_in_skills(stmt, db_session)

    if policy == SkillManagementPolicy.EDIT:
        stmt = stmt.where(Skill.built_in_skill_id.is_(None))
        if has_global_permission(user, Permission.MANAGE_SKILLS):
            return stmt
        return stmt.where(_is_editable_by_user(user))

    raise ValueError(f"Unknown skill management policy: {policy}")


def get_group_ids_for_skill(skill_id: UUID, db_session: Session) -> list[int]:
    """Group ids a skill is shared with — the scope input for GATE 2 checks."""
    return list(
        db_session.scalars(
            select(Skill__UserGroup.user_group_id).where(
                Skill__UserGroup.skill_id == skill_id
            )
        )
    )


def affected_user_ids_for_skill(skill: Skill, db_session: Session) -> set[UUID]:
    return affected_user_ids_for_skills([skill.id], db_session).get(skill.id, set())


def affected_user_ids_for_skills(
    skill_ids: Collection[UUID], db_session: Session
) -> dict[UUID, set[UUID]]:
    recipients: dict[UUID, set[UUID]] = {}
    if not skill_ids:
        return recipients
    direct = exists().where(
        Skill__User.skill_id == Skill.id, Skill__User.user_id == Sandbox.user_id
    )
    group = (
        select(Skill__UserGroup.skill_id)
        .join(
            User__UserGroup,
            User__UserGroup.user_group_id == Skill__UserGroup.user_group_id,
        )
        .where(
            Skill__UserGroup.skill_id == Skill.id,
            User__UserGroup.user_id == Sandbox.user_id,
        )
        .exists()
    )
    rows = db_session.execute(
        select(Skill.id, Sandbox.user_id)
        .join(
            Sandbox,
            and_(
                Sandbox.status == SandboxStatus.RUNNING,
                or_(
                    Skill.public_permission.is_not(None),
                    Skill.author_user_id == Sandbox.user_id,
                    direct,
                    group,
                ),
            ),
        )
        .where(Skill.id.in_(skill_ids))
    )
    for skill_id, user_id in rows:
        recipients.setdefault(skill_id, set()).add(user_id)
    return recipients


def list_skills(
    *,
    policy: SkillManagementPolicy,
    db_session: Session,
    user: User,
) -> list[Skill]:
    stmt = _skill_select_for_management_policy(
        policy=policy,
        db_session=db_session,
        user=user,
        order_by_name=True,
    )
    return list(db_session.scalars(stmt))


def list_runtime_skills_for_user(
    *,
    db_session: Session,
    user: User,
) -> list[Skill]:
    """Return the user's effective sandbox skills.

    Management visibility, user selection, bundle validity, built-in
    availability, and external-app readiness remain independent inputs.
    """
    external_app_dependencies = get_skill_external_app_dependencies(db_session, user)
    ready_external_app_skill_ids = [
        skill_id
        for skill_id, dependency in external_app_dependencies.items()
        if dependency.ready
    ]
    stmt = _skill_select_with_eager_load(order_by_name=True).where(
        skill_visible_to_user(user),
        _is_enabled_for_user(user),
        or_(
            ~exists().where(ExternalApp__Skill.skill_id == Skill.id),
            Skill.id.in_(ready_external_app_skill_ids),
        ),
        or_(
            Skill.built_in_skill_id.isnot(None),
            and_(SkillVersion.id.is_not(None), SkillVersion.is_valid.is_not(False)),
        ),
    )
    return list(
        db_session.scalars(_exclude_unavailable_built_in_skills(stmt, db_session))
    )


def fetch_skill(
    skill_id: UUID,
    *,
    policy: SkillManagementPolicy,
    db_session: Session,
    user: User,
    lock_for_update: bool = False,
) -> Skill | None:
    stmt = _skill_select_for_management_policy(
        policy=policy,
        db_session=db_session,
        user=user,
        order_by_name=False,
    ).where(Skill.id == skill_id)
    if lock_for_update:
        stmt = stmt.with_for_update(of=Skill).execution_options(populate_existing=True)
    skill = db_session.scalars(stmt).one_or_none()
    if skill is not None and lock_for_update:
        db_session.refresh(skill, ["current_version"])
    return skill


def add_new_skill__no_commit(
    skill: Skill,
    db_session: Session,
) -> Skill:
    db_session.add(skill)
    db_session.flush()
    return skill


def _lock_user_skill_preferences(user_id: UUID, db_session: Session) -> None:
    # Serialize preference changes without blocking foreign-key reads from sharing.
    db_session.execute(
        select(User.__table__.c.id)
        .where(User.__table__.c.id == user_id)
        .with_for_update(key_share=True)
    )


def enable_new_skill_if_name_available__no_commit(
    skill: Skill,
    user_id: UUID,
    db_session: Session,
) -> bool:
    """Enable a newly inserted skill under the same user lock as toggles."""
    _lock_user_skill_preferences(user_id, db_session)
    user = db_session.get(User, user_id)
    if user is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "User not found.")
    if skill.installation_policy == SkillInstallationPolicy.REQUIRED:
        return True
    if (
        db_session.scalar(
            select(Skill.id).where(
                Skill.name == skill.name,
                Skill.id != skill.id,
                _is_enabled_for_user(user),
            )
        )
        is not None
    ):
        return False
    inserted_user_id = db_session.scalar(
        insert(UserSkillPreference)
        .values(user_id=user_id, skill_id=skill.id, name=skill.name, enabled=True)
        .on_conflict_do_nothing()
        .returning(UserSkillPreference.user_id)
    )
    return inserted_user_id is not None


def replace_skill_bundle(
    *,
    skill: Skill,
    ingested: IngestedBundle,
    creator_id: UUID,
    db_session: Session,
) -> list[str]:
    """Keep history and legacy columns; return the files to delete after commit."""
    if not skill.is_custom:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Built-in skills have no bundle.")
    return save_skill_version(skill, ingested, creator_id, db_session)


def create_skill_from_ingested_bundle(
    ingested: IngestedBundle, creator_id: UUID, db_session: Session
) -> Skill:
    skill = add_new_skill__no_commit(
        Skill(
            name=ingested.canonical_name,
            description=ingested.description,
            bundle_file_id=ingested.bundle_file_id,
            bundle_sha256=ingested.bundle_sha256,
            is_valid=True,
            author_user_id=creator_id,
        ),
        db_session,
    )
    save_skill_version(skill, ingested, creator_id, db_session, initial=True)
    return skill


def set_skill_public_permission(
    *,
    skill: Skill,
    public_permission: SkillSharePermission | None,
    db_session: Session,
) -> None:
    is_associated = db_session.scalar(
        select(
            exists().where(
                ExternalApp__Skill.skill_id == skill.id,
            )
        )
    )
    if is_associated and public_permission != SkillSharePermission.VIEWER:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Skills associated with an external app must remain visible to the "
            "organization with viewer access.",
        )
    if public_permission is None and skill.is_custom and skill.author_user_id is None:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "Assign an owner before making this skill private.",
        )
    skill.public_permission = public_permission
    db_session.flush()


def skill_user_states(
    user: User,
    skill_ids: Iterable[UUID],
    db_session: Session,
) -> dict[UUID, SkillUserState]:
    requested_ids = set(skill_ids)
    if not requested_ids:
        return {}

    external_app_dependencies = get_skill_external_app_dependencies(
        db_session,
        user,
        requested_ids,
    )
    rows = db_session.execute(
        select(
            Skill.id,
            _is_enabled_for_user(user).label("enabled"),
            skill_visible_to_user(user).label("visible"),
            and_(
                Skill.built_in_skill_id.is_(None),
                SkillVersion.id.is_not(None),
                SkillVersion.is_valid.is_not(False),
                Skill.installation_policy != SkillInstallationPolicy.REQUIRED,
            ).label("supports_preference"),
        )
        .outerjoin(Skill.current_version)
        .where(Skill.id.in_(requested_ids))
    )
    return {
        skill_id: SkillUserState(
            enabled=enabled,
            can_toggle=visible
            and supports_preference
            and (
                enabled
                or skill_id not in external_app_dependencies
                or external_app_dependencies[skill_id].ready
            ),
            external_app_dependency=external_app_dependencies.get(skill_id),
        )
        for skill_id, enabled, visible, supports_preference in rows
    }


def set_skill_enabled_for_user(
    *,
    skill_id: UUID,
    enabled: bool,
    replace_conflict: bool = False,
    user: User,
    db_session: Session,
) -> Skill:
    _lock_user_skill_preferences(user.id, db_session)
    skill = fetch_skill(
        skill_id,
        policy=SkillManagementPolicy.VIEW,
        user=user,
        db_session=db_session,
        lock_for_update=True,
    )
    if skill is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            "Skill is not visible.",
        )

    state = skill_user_states(user, [skill.id], db_session)[skill.id]
    if not state.can_toggle:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "This skill cannot be enabled or disabled.",
        )

    if enabled:
        required = db_session.scalar(
            select(Skill.id).where(
                Skill.name == skill.name,
                Skill.id != skill.id,
                _is_required_for_user(user),
            )
        )
        if required is not None:
            raise OnyxError(
                OnyxErrorCode.SKILL_NAME_CONFLICT,
                "A required skill already uses this name.",
            )
        conflicts = db_session.scalars(
            select(Skill.id).where(
                Skill.name == skill.name,
                Skill.id != skill.id,
                _is_enabled_for_user(user),
            )
        ).all()
        if conflicts:
            if not replace_conflict:
                raise OnyxError(
                    OnyxErrorCode.SKILL_NAME_CONFLICT,
                    f"Another skill named '{skill.name}' is already enabled.",
                )
            db_session.execute(
                insert(UserSkillPreference)
                .values(
                    [
                        {
                            "user_id": user.id,
                            "skill_id": conflict,
                            "name": skill.name,
                            "enabled": False,
                        }
                        for conflict in conflicts
                    ]
                )
                .on_conflict_do_update(
                    index_elements=[
                        UserSkillPreference.user_id,
                        UserSkillPreference.skill_id,
                    ],
                    set_={"enabled": False},
                )
            )
    db_session.execute(
        insert(UserSkillPreference)
        .values(user_id=user.id, skill_id=skill.id, name=skill.name, enabled=enabled)
        .on_conflict_do_update(
            index_elements=[UserSkillPreference.user_id, UserSkillPreference.skill_id],
            set_={"enabled": enabled},
        )
    )
    return skill


def set_skill_installation_policy(
    skill: Skill,
    policy: SkillInstallationPolicy,
    db_session: Session,
) -> None:
    if policy != SkillInstallationPolicy.AVAILABLE and not skill.is_custom:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Installation policies apply only to custom skills.",
        )
    try:
        with db_session.begin_nested():
            skill.installation_policy = policy
            db_session.flush()
    except IntegrityError as exc:
        if not is_unique_violation(exc, "uq_skill_automatic_name"):
            raise
        raise OnyxError(
            OnyxErrorCode.SKILL_NAME_CONFLICT,
            "Another automatically installed skill already uses this name.",
        ) from exc


def _flush_shares(db_session: Session, fk_violation_detail: str) -> None:
    try:
        db_session.flush()
    except IntegrityError as e:
        if is_fk_violation(e):
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, fk_violation_detail) from e
        raise


def replace_skill_shares(
    *,
    skill: Skill,
    db_session: Session,
    user_shares: Mapping[UUID, SkillSharePermission] | None = None,
    group_shares: Mapping[int, SkillSharePermission] | None = None,
) -> None:
    if user_shares is not None:
        db_session.execute(delete(Skill__User).where(Skill__User.skill_id == skill.id))
        for user_id, permission in user_shares.items():
            db_session.add(
                Skill__User(skill_id=skill.id, user_id=user_id, permission=permission)
            )
        _flush_shares(db_session, "One or more user share targets do not exist.")
        db_session.expire(skill, ["user_shares"])

    if group_shares is not None:
        assert_not_shared_with_default_group(db_session, list(group_shares))
        db_session.execute(
            delete(Skill__UserGroup).where(Skill__UserGroup.skill_id == skill.id)
        )
        for group_id, permission in group_shares.items():
            db_session.add(
                Skill__UserGroup(
                    skill_id=skill.id,
                    user_group_id=group_id,
                    permission=permission,
                )
            )
        _flush_shares(db_session, "One or more group share targets do not exist.")
        db_session.expire(skill, ["group_shares"])


def transfer_skill_ownership(
    *,
    skill: Skill,
    new_owner_user_id: UUID,
    db_session: Session,
) -> None:
    if not skill.is_custom:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Skill '{skill.name}' is a built-in and cannot have its ownership transferred.",
        )

    previous_owner_user_id = skill.author_user_id
    if new_owner_user_id == previous_owner_user_id:
        return

    try:
        skill.author_user_id = new_owner_user_id
        db_session.execute(
            delete(Skill__User).where(
                Skill__User.skill_id == skill.id,
                Skill__User.user_id == new_owner_user_id,
            )
        )
        if previous_owner_user_id is not None:
            share_upsert = (
                insert(Skill__User)
                .values(
                    skill_id=skill.id,
                    user_id=previous_owner_user_id,
                    permission=SkillSharePermission.EDITOR,
                )
                .on_conflict_do_update(
                    index_elements=[Skill__User.skill_id, Skill__User.user_id],
                    set_={"permission": SkillSharePermission.EDITOR},
                )
                .returning(Skill__User)
            )
            db_session.scalars(
                share_upsert,
                execution_options={"populate_existing": True},
            ).one()
        db_session.flush()
    except IntegrityError as e:
        if is_fk_violation(e):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "New owner user does not exist.",
            ) from e
        raise


def delete_skill(skill: Skill, db_session: Session) -> list[str]:
    """Hard-delete a locked skill and its versions. Returns every bundle file id
    for cleanup after commit."""
    file_ids = skill_bundle_file_ids(skill, db_session)
    db_session.delete(skill)
    db_session.flush()
    return sorted(file_ids)


def persist_skill_validity(
    updates: Iterable[SkillValidityUpdate],
) -> None:
    """Persist classifications if each skill still references the observed bundle."""
    if not updates:
        return

    with get_session_with_current_tenant() as db_session:
        for validity_update in updates:
            persist_skill_version_validity(
                skill_id=validity_update.skill_id,
                version_id=validity_update.version_id,
                bundle_file_id=validity_update.bundle_file_id,
                is_valid=validity_update.is_valid,
                db_session=db_session,
            )
        db_session.commit()


SkillBulkAction = Literal["enable", "disable", "delete"]


def ensure_can_edit_org_visibility(user: User) -> None:
    if not has_global_permission(user, Permission.MANAGE_SKILLS):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Company access changes require global manage-skills permission.",
        )


class SkillAccessAdapter(ResourceAccessAdapter[Skill]):
    permission = Permission.MANAGE_SKILLS

    def load(self, resource_id: UUID, user: User, db_session: Session) -> Skill:
        skill = fetch_skill(
            resource_id,
            policy=SkillManagementPolicy.EDIT,
            user=user,
            db_session=db_session,
            lock_for_update=True,
        )
        if skill is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
        return skill

    def state(self, resource: Skill) -> ResourceAccessState:
        return ResourceAccessState(
            owner_user_id=resource.author_user_id,
            public_permission=resource.public_permission,
            user_shares={
                share.user_id: share.permission for share in resource.user_shares
            },
            group_shares={
                share.user_group_id: share.permission for share in resource.group_shares
            },
        )

    def write(
        self, resource: Skill, change: SkillSharingChange, db_session: Session
    ) -> None:
        if change.set_public_permission:
            set_skill_public_permission(
                skill=resource,
                public_permission=change.public_permission,
                db_session=db_session,
            )
        if change.installation_policy is not None:
            set_skill_installation_policy(
                resource, change.installation_policy, db_session
            )
        replace_skill_shares(
            skill=resource,
            user_shares=change.user_shares,
            group_shares=change.group_shares,
            db_session=db_session,
        )

    def affected_users(
        self, resource_ids: Collection[UUID], db_session: Session
    ) -> dict[UUID, set[UUID]]:
        return affected_user_ids_for_skills(resource_ids, db_session)


def share_skill__no_commit(
    skill: Skill,
    change: SkillSharingChange,
    user: User,
    db_session: Session,
) -> set[UUID]:
    return mutate_resource_access(
        [skill.id],
        change,
        user,
        db_session,
        SkillAccessAdapter(),
    ).affected


def delete_skill_for_user__no_commit(
    skill: Skill, user: User, db_session: Session
) -> tuple[set[UUID], list[str]]:
    """Delete a skill the user may edit. Returns the affected users and the
    bundle file ids for cleanup after commit."""
    if (
        skill.installation_policy == SkillInstallationPolicy.REQUIRED
        and not has_global_permission(user, Permission.MANAGE_SKILLS)
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Deleting required skills requires global manage-skills permission.",
        )
    affected = affected_user_ids_for_skill(skill, db_session)
    return affected, delete_skill(skill, db_session)


def create_skill_from_bundle__no_commit(
    ingested: IngestedBundle,
    change: SkillSharingChange | None,
    auto_enable: bool,
    user: User,
    db_session: Session,
) -> tuple[Skill, bool, set[UUID]]:
    """Create a skill from a stored bundle inside a savepoint, so a name
    conflict or a rejected access change rolls back this skill only. Returns
    the skill, whether it was enabled for the user, and the affected users."""
    with db_session.begin_nested():
        skill = create_skill_from_ingested_bundle(ingested, user.id, db_session)
        affected: set[UUID] = set()
        if change is not None:
            affected = share_skill__no_commit(skill, change, user, db_session)
        enabled = auto_enable and enable_new_skill_if_name_available__no_commit(
            skill, user.id, db_session
        )
        if enabled:
            affected.add(user.id)
    return skill, enabled, affected


def bulk_update_skill__no_commit(
    skill_id: UUID,
    action: SkillBulkAction,
    user: User,
    db_session: Session,
) -> tuple[set[UUID], list[str]]:
    """Apply one bulk action to one skill inside a savepoint, so a failure
    rolls back this skill only. Returns the affected users and, for a delete,
    the bundle file ids for cleanup after commit."""
    with db_session.begin_nested():
        if action in ("enable", "disable"):
            set_skill_enabled_for_user(
                skill_id=skill_id,
                enabled=action == "enable",
                user=user,
                db_session=db_session,
            )
            return {user.id}, []
        skill = fetch_skill(
            skill_id,
            policy=SkillManagementPolicy.EDIT,
            user=user,
            db_session=db_session,
            lock_for_update=True,
        )
        if skill is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
        return delete_skill_for_user__no_commit(skill, user, db_session)
