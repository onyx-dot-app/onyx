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

Delete is a hard delete — `delete_skill` removes the row and its plugin and
returns its `bundle_file_id` so the caller can drop the blob from the file
store immediately.

Each custom skill is also a plugin of kind skill with the same id
(`onyx.db.plugin`). Every write goes to both: the plugin rows and the legacy
skill rows, which old readers still use. A bundle change adds a plugin version
and never deletes the previous bundle. Access writes (shares, publishing, the
install setting, user choices, transfer) call one `onyx.db.plugin` helper for
each legacy write. Publishing is one-way, and there is no organization-wide
edit.

Mutation helpers do not commit unless their docstring explicitly says otherwise.
Callers normally control the transaction boundary so multi-step operations can
roll back atomically.
"""

from collections.abc import Callable, Iterable, Mapping
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
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from onyx.auth.permissions import has_global_permission, has_permission
from onyx.auth.scoped_permissions import assert_within_scope
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
    associate_custom_skill_with_external_app__no_commit,
    get_skill_external_app_dependencies,
)
from onyx.db.models import (
    ExternalApp__Skill,
    PluginVersion,
    Sandbox,
    Skill,
    Skill__User,
    Skill__UserGroup,
    User,
    User__UserGroup,
    UserSkillPreference,
)
from onyx.db.plugin import (
    add_plugin_version__no_commit,
    create_skill_plugin__no_commit,
    delete_plugin__no_commit,
    lock_skill_plugin__no_commit,
    persist_plugin_version_validity__no_commit,
    publish_plugin__no_commit,
    replace_plugin_group_shares__no_commit,
    replace_plugin_user_shares__no_commit,
    set_plugin_installation_policy__no_commit,
    set_plugin_preferences__no_commit,
    set_plugin_user_share__no_commit,
    transfer_plugin__no_commit,
)
from onyx.db.scoped_permissions import (
    scoped_group_ids_subquery,
    within_managed_scope_clause,
)
from onyx.db.user_group import assert_not_shared_with_default_group
from onyx.db.utils import is_fk_violation, is_unique_violation
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.ingest import IngestedBundle
from onyx.skills.models import PluginFileEntry


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
    stmt = select(Skill).options(
        selectinload(Skill.author),
        selectinload(Skill.user_shares).selectinload(Skill__User.user),
        selectinload(Skill.group_shares).selectinload(Skill__UserGroup.user_group),
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
    stmt = _skill_select_with_eager_load(order_by_name=True).where(
        skill_visible_to_user(user),
        _is_enabled_for_user(user),
        or_(
            ~exists().where(ExternalApp__Skill.skill_id == Skill.id),
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
    if inserted_user_id is None:
        return False
    if skill.is_custom:
        plugin = lock_skill_plugin__no_commit(skill, db_session)
        set_plugin_preferences__no_commit(user_id, [plugin.id], True, db_session)
    return True


def create_custom_skill__no_commit(
    ingested: IngestedBundle,
    user: User,
    db_session: Session,
    *,
    change: "SkillSharingChange | None" = None,
    external_app_id: int | None = None,
) -> tuple[Skill, set[UUID]]:
    """Create a custom skill: the legacy skill row, then its plugin, version 1
    and plugin_skill row with the same id, in the caller's transaction. A skill
    created public (or for an app) starts in the Organization library and takes
    the next free name there, as main allows two public skills with one name;
    others start in the author's "My uploads". Returns the skill and the users
    the access change affects."""
    created_public = external_app_id is not None or (
        change is not None
        and change.set_public_permission
        and change.public_permission == SkillSharePermission.VIEWER
    )
    skill = add_new_skill__no_commit(
        Skill(
            name=ingested.canonical_name,
            description=ingested.description,
            bundle_file_id=ingested.bundle_file_id,
            bundle_sha256=ingested.bundle_sha256,
            is_valid=True,
            author_user_id=user.id,
            public_permission=(SkillSharePermission.VIEWER if created_public else None),
        ),
        db_session,
    )
    create_skill_plugin__no_commit(skill, ingested.content, user, db_session)
    if external_app_id is not None:
        associate_custom_skill_with_external_app__no_commit(
            db_session,
            external_app_id=external_app_id,
            skill_id=skill.id,
        )
    affected: set[UUID] = set()
    if change is not None:
        affected = share_skill__no_commit(skill, change, user, db_session)
    return skill, affected


def replace_skill_bundle(
    *,
    skill: Skill,
    ingested: IngestedBundle,
    base_version_id: UUID | None,
    user: User,
    skip_if_unchanged: bool,
    db_session: Session,
    previous_manifest: Callable[[], list[PluginFileEntry]] | None = None,
) -> PluginVersion | None:
    """Add a plugin version with the new bundle and keep the legacy skill row
    current. The caller holds the skill row lock (``lock_for_update``).

    Returns None, and changes nothing, when ``skip_if_unchanged`` is set and
    the files did not change; the caller then deletes the new blob. The
    previous bundle stays: older versions still point at it.

    Rejects built-in rows — they have no bundle.
    """
    if not skill.is_custom:
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

    # A skill with no plugin gets one copied from its legacy row first, so the
    # change below is version 2, as for every other skill.
    plugin = lock_skill_plugin__no_commit(skill, db_session)
    version = add_plugin_version__no_commit(
        plugin=plugin,
        content=ingested.content,
        base_version_id=base_version_id,
        created_by=user,
        skip_if_unchanged=skip_if_unchanged,
        previous_manifest=previous_manifest,
        db_session=db_session,
    )
    if version is None:
        return None

    skill.bundle_file_id = ingested.bundle_file_id
    skill.bundle_sha256 = ingested.bundle_sha256
    skill.name = ingested.canonical_name
    skill.description = ingested.description
    skill.is_valid = True
    db_session.flush()
    return version


def set_skill_public_permission(
    *,
    skill: Skill,
    public_permission: SkillSharePermission | None,
    db_session: Session,
) -> None:
    """Publish a custom skill to the organization (VIEWER), or keep it
    private (None). Every route that changes organization access calls this.

    Publishing moves the plugin to the Organization library, and a name clash
    there is refused with CONFLICT. Publishing is one-way: a published skill
    cannot become private. Organization-wide EDITOR is refused; editors are
    named users and groups."""
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
    if not skill.is_custom:
        skill.public_permission = public_permission
        db_session.flush()
        return
    if public_permission == SkillSharePermission.EDITOR:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "The organization cannot get edit access to a skill. Share it with "
            "users or groups as editors instead.",
        )
    if public_permission is None:
        if skill.public_permission is not None:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "This skill is published to the organization. Publishing cannot "
                "be undone, so the skill cannot be made private.",
            )
        return
    plugin = lock_skill_plugin__no_commit(skill, db_session)
    skill.public_permission = public_permission
    db_session.flush()
    publish_plugin__no_commit(plugin.id, "raise", db_session)


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
                Skill.is_valid.is_not(False),
                Skill.installation_policy != SkillInstallationPolicy.REQUIRED,
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

    conflicts: list[UUID] = []
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
        conflicts = list(
            db_session.scalars(
                select(Skill.id).where(
                    Skill.name == skill.name,
                    Skill.id != skill.id,
                    _is_enabled_for_user(user),
                )
            )
        )
        if conflicts and not replace_conflict:
            raise OnyxError(
                OnyxErrorCode.SKILL_NAME_CONFLICT,
                f"Another skill named '{skill.name}' is already enabled.",
            )
    # One id order for the target and its conflicts, so two users who switch
    # between the same skills cannot deadlock on the plugin rows.
    conflict_plugin_ids = [
        plugin_id
        for plugin_id in _lock_custom_skill_plugins([skill.id, *conflicts], db_session)
        if plugin_id != skill.id
    ]
    if conflicts:
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
        set_plugin_preferences__no_commit(
            user.id, conflict_plugin_ids, False, db_session
        )
    db_session.execute(
        insert(UserSkillPreference)
        .values(user_id=user.id, skill_id=skill.id, name=skill.name, enabled=enabled)
        .on_conflict_do_update(
            index_elements=[UserSkillPreference.user_id, UserSkillPreference.skill_id],
            set_={"enabled": enabled},
        )
    )
    set_plugin_preferences__no_commit(user.id, [skill.id], enabled, db_session)
    return skill


def _lock_custom_skill_plugins(
    skill_ids: Iterable[UUID], db_session: Session
) -> list[UUID]:
    """Lock the plugins of the custom skills among ``skill_ids``, in id order,
    and return their ids. Built-in skills have no plugin."""
    ids = set(skill_ids)
    if not ids:
        return []
    skills = db_session.scalars(
        select(Skill)
        .where(Skill.id.in_(ids), Skill.built_in_skill_id.is_(None))
        .order_by(Skill.id)
    ).all()
    return [lock_skill_plugin__no_commit(skill, db_session).id for skill in skills]


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
    plugin = (
        lock_skill_plugin__no_commit(skill, db_session) if skill.is_custom else None
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
    if plugin is not None:
        set_plugin_installation_policy__no_commit(plugin.id, policy, db_session)


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
    plugin_id = (
        lock_skill_plugin__no_commit(skill, db_session).id
        if skill.is_custom and (user_shares is not None or group_shares is not None)
        else None
    )
    if user_shares is not None:
        db_session.execute(delete(Skill__User).where(Skill__User.skill_id == skill.id))
        for user_id, permission in user_shares.items():
            db_session.add(
                Skill__User(skill_id=skill.id, user_id=user_id, permission=permission)
            )
        _flush_shares(db_session, "One or more user share targets do not exist.")
        db_session.expire(skill, ["user_shares"])
        if plugin_id is not None:
            replace_plugin_user_shares__no_commit(plugin_id, user_shares, db_session)

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
        if plugin_id is not None:
            replace_plugin_group_shares__no_commit(plugin_id, group_shares, db_session)


def transfer_skill_ownership(
    *,
    skill: Skill,
    new_owner_user_id: UUID,
    db_session: Session,
) -> None:
    """Make another user the owner. The previous owner keeps EDITOR. A private
    skill moves to the new owner's "My uploads", and a name clash there is
    refused with CONFLICT. A published skill stays published."""
    if not skill.is_custom:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Skill '{skill.name}' is a built-in and cannot have its ownership transferred.",
        )

    previous_owner_user_id = skill.author_user_id
    if new_owner_user_id == previous_owner_user_id:
        return

    plugin = lock_skill_plugin__no_commit(skill, db_session)
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
    transfer_plugin__no_commit(plugin.id, new_owner_user_id, db_session)
    set_plugin_user_share__no_commit(plugin.id, new_owner_user_id, None, db_session)
    if previous_owner_user_id is not None:
        set_plugin_user_share__no_commit(
            plugin.id,
            previous_owner_user_id,
            SkillSharePermission.EDITOR,
            db_session,
        )


def delete_skill(skill: Skill, db_session: Session) -> str | None:
    """Hard-delete a skill and its plugin, and return its current
    `bundle_file_id` for caller cleanup."""
    bundle_file_id = skill.bundle_file_id
    if skill.is_custom:
        delete_plugin__no_commit(skill.id, db_session)
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
            persist_plugin_version_validity__no_commit(
                plugin_id=validity_update.skill_id,
                bundle_file_id=validity_update.bundle_file_id,
                is_valid=validity_update.is_valid,
                db_session=db_session,
            )
        db_session.commit()


@dataclass(frozen=True)
class SkillSharingChange:
    """A partial update to a skill's access. None leaves a setting unchanged;
    set_public_permission marks public_permission as supplied."""

    public_permission: SkillSharePermission | None = None
    set_public_permission: bool = False
    installation_policy: SkillInstallationPolicy | None = None
    user_shares: Mapping[UUID, SkillSharePermission] | None = None
    group_shares: Mapping[int, SkillSharePermission] | None = None


SkillBulkAction = Literal["share", "enable", "disable", "delete"]


def ensure_can_edit_org_visibility(skill: Skill, user: User) -> None:
    if skill.author_user_id == user.id:
        return
    if has_global_permission(user, Permission.MANAGE_SKILLS):
        return
    raise OnyxError(
        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
        "You do not have permission to change organization-wide skill access.",
    )


def _assert_group_share_within_scope(
    skill: Skill,
    change: SkillSharingChange,
    user: User,
    db_session: Session,
) -> None:
    """Changing a skill's group shares is a MANAGE_SKILLS action, matching how
    agents treat group attachment. EDIT on the skill is not enough: an owner
    could otherwise publish into any group and inject the skill into that group
    manager's scope. Shares are read from the DB, never the request, so a
    reassignment cannot escape scope. Re-sending the current set is a no-op."""
    if change.group_shares is None:
        return
    current = {share.user_group_id: share.permission for share in skill.group_shares}
    if current == dict(change.group_shares):
        return
    assert_within_scope(
        user,
        db_session,
        permission=Permission.MANAGE_SKILLS,
        current_group_ids=list(current),
        requested_group_ids=list(change.group_shares),
        is_non_public=skill.public_permission is None
        and change.public_permission is None,
    )


def share_skill__no_commit(
    skill: Skill,
    change: SkillSharingChange,
    user: User,
    db_session: Session,
    *,
    merge_existing: bool = False,
) -> set[UUID]:
    """Apply an access change and return every user whose sandbox is affected,
    before or after the change. With merge_existing, supplied user and group
    grants are added to the current ones instead of replacing them."""
    if change.installation_policy is not None and not has_global_permission(
        user, Permission.FULL_ADMIN_PANEL_ACCESS
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Only admins can change skill installation policies.",
        )
    if change.set_public_permission:
        ensure_can_edit_org_visibility(skill, user)
    # Anchor on the pre-call visibility so a public->private convert plus a
    # group-share in one request can't slip a published skill into managed scope.
    _assert_group_share_within_scope(skill, change, user, db_session)

    before = affected_user_ids_for_skill(skill, db_session)
    if change.set_public_permission:
        set_skill_public_permission(
            skill=skill,
            public_permission=change.public_permission,
            db_session=db_session,
        )
    if change.installation_policy is not None:
        set_skill_installation_policy(skill, change.installation_policy, db_session)

    user_shares: dict[UUID, SkillSharePermission] | None = None
    if change.user_shares is not None:
        user_shares = {
            user_id: permission
            for user_id, permission in change.user_shares.items()
            if user_id != skill.author_user_id
        }
        if merge_existing:
            user_shares = {
                share.user_id: share.permission for share in skill.user_shares
            } | user_shares
    group_shares: dict[int, SkillSharePermission] | None = None
    if change.group_shares is not None:
        group_shares = dict(change.group_shares)
        if merge_existing:
            group_shares = {
                share.user_group_id: share.permission for share in skill.group_shares
            } | group_shares
    replace_skill_shares(
        skill=skill,
        user_shares=user_shares,
        group_shares=group_shares,
        db_session=db_session,
    )
    return before | affected_user_ids_for_skill(skill, db_session)


def delete_skill_for_user__no_commit(
    skill: Skill, user: User, db_session: Session
) -> tuple[set[UUID], str | None]:
    """Delete a skill the user may edit. Only a user with organization-wide
    MANAGE_SKILLS can delete a published skill. Returns the affected users and
    the bundle file id for caller cleanup."""
    if skill.public_permission is not None and not has_global_permission(
        user, Permission.MANAGE_SKILLS
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "This skill is published to the organization. Only an admin can delete it.",
        )
    if (
        skill.installation_policy == SkillInstallationPolicy.REQUIRED
        and not has_global_permission(user, Permission.FULL_ADMIN_PANEL_ACCESS)
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Only admins can delete required skills.",
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
        skill, affected = create_custom_skill__no_commit(
            ingested, user, db_session, change=change
        )
        enabled = auto_enable and enable_new_skill_if_name_available__no_commit(
            skill, user.id, db_session
        )
        if enabled:
            affected.add(user.id)
    return skill, enabled, affected


def bulk_update_skill__no_commit(
    skill_id: UUID,
    action: SkillBulkAction,
    change: SkillSharingChange | None,
    user: User,
    db_session: Session,
) -> tuple[set[UUID], str | None]:
    """Apply one bulk action to one skill inside a savepoint, so a failure
    rolls back this skill only. Returns the affected users and, for a delete,
    the bundle file id for caller cleanup."""
    with db_session.begin_nested():
        if action in ("enable", "disable"):
            set_skill_enabled_for_user(
                skill_id=skill_id,
                enabled=action == "enable",
                user=user,
                db_session=db_session,
            )
            return {user.id}, None
        skill = fetch_skill(
            skill_id,
            policy=SkillManagementPolicy.EDIT,
            user=user,
            db_session=db_session,
            lock_for_update=True,
        )
        if skill is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
        if action == "share":
            if change is None:
                raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Sharing is required.")
            return share_skill__no_commit(
                skill, change, user, db_session, merge_existing=True
            ), None
        return delete_skill_for_user__no_commit(skill, user, db_session)
