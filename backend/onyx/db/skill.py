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

Delete is a hard delete — `delete_skill` removes the row and returns its
`bundle_file_id` so the caller can drop the blob from the file store
immediately (skills sync via S3-backed bundles, so blob retention isn't
needed).

Mutation helpers do not commit unless their docstring explicitly says otherwise.
Callers normally control the transaction boundary so multi-step operations can
roll back atomically.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Select,
    and_,
    delete,
    exists,
    func,
    or_,
    select,
    true,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from onyx.auth.schemas import UserRole
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import SandboxStatus, SkillSharePermission
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
    User,
    User__UserGroup,
    UserSkillPreference,
)
from onyx.db.utils import is_fk_violation
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.built_in import BUILT_IN_SKILLS


class SkillManagementPolicy(str, Enum):
    VIEW = "view"
    EDIT = "edit"


@dataclass(frozen=True)
class SkillValidityUpdate:
    skill_id: UUID
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


def _is_group_shared_only_with_curator_scope(user: User) -> ColumnElement[bool]:
    """Curators can manage skills only when all group shares are in their scope."""
    curator_scope_group_ids = select(User__UserGroup.user_group_id).where(
        User__UserGroup.user_id == user.id
    )
    share_in_curator_scope_exists = (
        select(Skill__UserGroup.skill_id)
        .join(
            User__UserGroup,
            User__UserGroup.user_group_id == Skill__UserGroup.user_group_id,
        )
        .where(Skill__UserGroup.skill_id == Skill.id)
        .where(User__UserGroup.user_id == user.id)
    )

    if user.role == UserRole.CURATOR:
        curator_scope_group_ids = curator_scope_group_ids.where(
            User__UserGroup.is_curator.is_(True)
        )
        share_in_curator_scope_exists = share_in_curator_scope_exists.where(
            User__UserGroup.is_curator.is_(True)
        )

    no_group_share_outside_scope = ~exists().where(
        Skill__UserGroup.skill_id == Skill.id
    ).where(Skill__UserGroup.user_group_id.notin_(curator_scope_group_ids)).correlate(
        Skill
    )
    return and_(share_in_curator_scope_exists.exists(), no_group_share_outside_scope)


def _is_owned_custom_skill(user: User) -> ColumnElement[bool]:
    return and_(
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
    if user.role in (UserRole.CURATOR, UserRole.GLOBAL_CURATOR):
        editable = or_(editable, _is_group_shared_only_with_curator_scope(user))
    return editable


def _is_enabled_for_user(user: User) -> ColumnElement[bool]:
    return or_(
        Skill.built_in_skill_id.isnot(None),
        exists(
            select(UserSkillPreference.user_id).where(
                UserSkillPreference.user_id == user.id,
                UserSkillPreference.skill_id == Skill.id,
            )
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
    stmt = select(Skill).options(
        selectinload(Skill.author),
        selectinload(Skill.user_shares).selectinload(Skill__User.user),
        selectinload(Skill.group_shares).selectinload(Skill__UserGroup.user_group),
    )
    if order_by_name:
        stmt = stmt.order_by(Skill.name, Skill.id)
    return stmt


def _has_external_app_dependency() -> ColumnElement[bool]:
    return exists().where(ExternalApp__Skill.skill_id == Skill.id)


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
                ~_has_external_app_dependency(),
            )
        )
        if user.role == UserRole.ADMIN:
            return stmt
        stmt = stmt.where(skill_visible_to_user(user))
        return _exclude_unavailable_built_in_skills(stmt, db_session)

    if policy == SkillManagementPolicy.EDIT:
        stmt = stmt.where(Skill.built_in_skill_id.is_(None))
        if user.role == UserRole.ADMIN:
            return stmt
        return stmt.where(_is_editable_by_user(user))

    raise ValueError(f"Unknown skill management policy: {policy}")


def affected_user_ids_for_skill(skill: Skill, db_session: Session) -> set[UUID]:
    """Return user IDs with a running sandbox that should contain this skill.

    Deliberately does not filter by user preference: disable/delete flows still
    need previous recipients so the push pipeline can remove the skill files.
    """
    if skill.public_permission is not None:
        stmt = select(Sandbox.user_id).where(Sandbox.status == SandboxStatus.RUNNING)
        return set(db_session.scalars(stmt))

    group_share_stmt = (
        select(Sandbox.user_id)
        .join(
            User__UserGroup,
            User__UserGroup.user_id == Sandbox.user_id,
        )
        .join(
            Skill__UserGroup,
            Skill__UserGroup.user_group_id == User__UserGroup.user_group_id,
        )
        .where(Skill__UserGroup.skill_id == skill.id)
        .where(Sandbox.status == SandboxStatus.RUNNING)
    )
    user_ids = set(db_session.scalars(group_share_stmt))

    user_share_stmt = (
        select(Sandbox.user_id)
        .join(
            Skill__User,
            Skill__User.user_id == Sandbox.user_id,
        )
        .where(Skill__User.skill_id == skill.id)
        .where(Sandbox.status == SandboxStatus.RUNNING)
    )
    user_ids |= set(db_session.scalars(user_share_stmt))

    if skill.author_user_id is not None:
        author_stmt = (
            select(Sandbox.user_id)
            .where(Sandbox.user_id == skill.author_user_id)
            .where(Sandbox.status == SandboxStatus.RUNNING)
        )
        user_ids |= set(db_session.scalars(author_stmt))

    return user_ids


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
    has_external_app_dependency = _has_external_app_dependency()
    stmt = _skill_select_with_eager_load(order_by_name=True).where(
        skill_visible_to_user(user),
        _is_enabled_for_user(user),
        or_(
            ~has_external_app_dependency,
            Skill.id.in_(ready_external_app_skill_ids),
        ),
        or_(
            Skill.built_in_skill_id.isnot(None),
            Skill.is_valid.is_(None),
            Skill.is_valid.is_(True),
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
        stmt = stmt.with_for_update(of=Skill)
    return db_session.scalars(stmt).one_or_none()


def add_new_skill__no_commit(
    skill: Skill,
    db_session: Session,
) -> Skill:
    db_session.add(skill)
    db_session.flush()
    return skill


def enable_new_skill_if_name_available__no_commit(
    skill: Skill,
    user_id: UUID,
    db_session: Session,
) -> bool:
    inserted_user_id = db_session.scalar(
        insert(UserSkillPreference)
        .values(user_id=user_id, skill_id=skill.id, name=skill.name)
        .on_conflict_do_nothing(
            index_elements=[
                UserSkillPreference.user_id,
                UserSkillPreference.name,
            ]
        )
        .returning(UserSkillPreference.user_id)
    )
    return inserted_user_id is not None


def replace_skill_bundle(
    *,
    skill: Skill,
    new_bundle_file_id: str,
    new_bundle_sha256: str,
    new_description: str,
    db_session: Session,
) -> str:
    """Swap a skill's bundle blob and refresh its description.

    Returns the old bundle file id so the caller can delete the old blob from
    FileStore after the transaction commits.

    Rejects built-in rows — they have no bundle.
    """
    if skill.built_in_skill_id is not None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Skill '{skill.name}' is a built-in and has no bundle.",
        )

    # Custom rows always have a bundle (XOR check constraint), but guard
    # explicitly rather than assert so a corrupt row fails loud, not silent.
    if skill.bundle_file_id is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Skill '{skill.name}' has no bundle to replace.",
        )

    old_bundle_file_id = skill.bundle_file_id
    skill.bundle_file_id = new_bundle_file_id
    skill.bundle_sha256 = new_bundle_sha256
    skill.description = new_description
    skill.is_valid = True
    db_session.flush()
    return old_bundle_file_id


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
            func.coalesce(skill_visible_to_user(user), False).label("visible"),
            and_(
                Skill.built_in_skill_id.is_(None),
                Skill.is_valid.is_not(False),
            ).label("supports_preference"),
        ).where(Skill.id.in_(requested_ids))
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

    if not enabled:
        db_session.execute(
            delete(UserSkillPreference).where(
                UserSkillPreference.user_id == user.id,
                UserSkillPreference.skill_id == skill.id,
            )
        )
        return skill

    preference_insert = insert(UserSkillPreference).values(
        user_id=user.id,
        skill_id=skill.id,
        name=skill.name,
    )
    enabled_skill_id = db_session.scalar(
        preference_insert.on_conflict_do_update(
            index_elements=[
                UserSkillPreference.user_id,
                UserSkillPreference.name,
            ],
            set_={"skill_id": preference_insert.excluded.skill_id},
            where=(
                true()
                if replace_conflict
                else UserSkillPreference.skill_id == preference_insert.excluded.skill_id
            ),
        ).returning(UserSkillPreference.skill_id)
    )
    if enabled_skill_id is None:
        raise OnyxError(
            OnyxErrorCode.SKILL_NAME_CONFLICT,
            f"Another skill named '{skill.name}' is already enabled.",
        )
    return skill


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

    if group_shares is not None:
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


def transfer_skill_ownership(
    *,
    skill: Skill,
    new_owner_user_id: UUID,
    db_session: Session,
) -> None:
    if skill.built_in_skill_id is not None:
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


def delete_skill(skill: Skill, db_session: Session) -> str | None:
    """Hard-delete a skill and return its `bundle_file_id` for caller cleanup."""
    bundle_file_id = skill.bundle_file_id
    db_session.delete(skill)
    db_session.flush()
    return bundle_file_id


def persist_skill_validity(
    updates: Iterable[SkillValidityUpdate],
) -> None:
    """Persist classifications if each skill still references the observed bundle."""
    if not updates:
        return

    with get_session_with_current_tenant() as db_session:
        for validity_update in updates:
            bundle_matches = (
                Skill.bundle_file_id == validity_update.bundle_file_id
                if validity_update.bundle_file_id is not None
                else Skill.bundle_file_id.is_(None)
            )
            db_session.execute(
                update(Skill)
                .where(
                    Skill.id == validity_update.skill_id,
                    bundle_matches,
                    Skill.is_valid.is_(None),
                )
                .values(is_valid=validity_update.is_valid)
            )
        db_session.commit()
