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
returns the bundle of its current version so the caller can drop the blob from
the file store immediately.

Each custom skill is also a plugin of kind skill with the same id
(`onyx.db.plugin`). Every write goes to both: the plugin rows and the legacy
skill rows, which a rollback still uses. Access, bundle and validity reads of
custom skills come from the plugin rows (`onyx.db.plugin_access`): each user
reads the version they run. Built-in skills have no plugin and keep their skill
rows. A bundle change adds a plugin version
and never deletes the previous bundle. Access writes (shares, publishing, the
install setting, user choices, transfer) call one `onyx.db.plugin` helper for
each legacy write. Publishing is one-way, and there is no organization-wide
edit.

Mutation helpers do not commit unless their docstring explicitly says otherwise.
Callers normally control the transaction boundary so multi-step operations can
roll back atomically.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Select,
    and_,
    exists,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, selectinload

from onyx.auth.permissions import has_global_permission, has_permission
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    Permission,
    PermissionAuthority,
    PluginInstallationPolicy,
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
    Marketplace,
    Plugin,
    Plugin__User,
    Plugin__UserGroup,
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
    AddedPluginVersion,
    NameClashAction,
    PluginAccessChange,
    PluginAccessMode,
    PluginGroupGrant,
    PluginGroupSetting,
    PluginUserGrant,
    add_plugin_version__no_commit,
    apply_plugin_access_change__no_commit,
    check_base_version,
    create_skill_plugin__no_commit,
    delete_plugin__no_commit,
    lock_skill_plugin__no_commit,
    persist_plugin_version_validity__no_commit,
    plugin_installation_policy,
    publish_or_request_review__no_commit,
    set_plugin_preferences__no_commit,
    transfer_plugin__no_commit,
)
from onyx.db.plugin_access import (
    HiddenSkillName,
    SkillNameOrder,
    SkillNameRank,
    UserPluginState,
    affected_user_ids_for_plugins,
    load_user_plugin_states,
    order_skill_names,
    plugin_editable_by_user,
    plugin_is_published,
    plugin_usage_by_plugin,
    plugin_visible_to_user,
    skill_name_in_version,
    skill_name_order_key,
    version_user_runs,
)
from onyx.db.plugin_review import (
    deny_review__no_commit,
    pending_version,
)
from onyx.db.scoped_permissions import (
    managed_group_member_ids_subquery,
    scoped_group_ids_subquery,
    within_managed_scope_clause,
)
from onyx.db.skill_limit import SkillLimitCheck, skill_limit_check
from onyx.db.utils import (
    UNSET,
    UnsetType,
    is_fk_violation,
    is_unique_violation,
)
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
class RuntimeSkillVersion:
    """The plugin version a user runs (``version_user_runs``)."""

    id: UUID
    bundle_file_id: str | None
    is_valid: bool | None


@dataclass(frozen=True)
class RuntimeSkill:
    skill: Skill
    # The name in the version the user runs; the row name for a built-in.
    name: str
    # None for a built-in skill.
    version: RuntimeSkillVersion | None
    # Place in the name order; BUILT_IN with no created_at for a built-in.
    name_rank: SkillNameRank
    plugin_created_at: datetime | None


@dataclass(frozen=True)
class SkillUserState:
    enabled: bool
    can_toggle: bool
    # The install setting for the user. None for a built-in or a skill the
    # user cannot see.
    installation_policy: PluginInstallationPolicy | None
    external_app_dependency: SkillExternalAppDependencyState | None
    # Set when the name order hides the skill for the user.
    name_hidden: HiddenSkillName | None


def _is_shared_with_user(
    user: User,
    permission: SkillSharePermission | None = None,
) -> ColumnElement[bool]:
    """Legacy share rows. Only built-in skills still read them."""
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
    """Legacy share rows. Only built-in skills still read them."""
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


type _PluginClause[T] = Callable[[type[Plugin], type[Marketplace]], ColumnElement[T]]


def _plugin_of_skill[T](build: _PluginClause[T]) -> Select[tuple[T]]:
    """Select ``build`` over the plugin of the enclosing query's skill. Fresh
    aliases, so the clause can nest inside another plugin query."""
    plugin: type[Plugin] = aliased(Plugin)
    marketplace: type[Marketplace] = aliased(Marketplace)
    return (
        select(build(plugin, marketplace))
        .select_from(plugin)
        .join(marketplace, marketplace.id == plugin.marketplace_id)
        .where(plugin.id == Skill.id)
        .correlate_except(plugin, marketplace)
    )


def _plugin_of_skill_matches(build: _PluginClause[bool]) -> ColumnElement[bool]:
    """True when the skill's plugin satisfies ``build``. False for a built-in
    skill or a custom skill with no plugin."""
    plugin: type[Plugin] = aliased(Plugin)
    marketplace: type[Marketplace] = aliased(Marketplace)
    return (
        select(plugin.id)
        .join(marketplace, marketplace.id == plugin.marketplace_id)
        .where(plugin.id == Skill.id, build(plugin, marketplace))
        .correlate_except(plugin, marketplace)
        .exists()
    )


def _is_published() -> ColumnElement[bool]:
    return _plugin_of_skill_matches(
        lambda _plugin, marketplace: plugin_is_published(marketplace)
    )


def _is_group_shared_only_within_managed_scope(user: User) -> ColumnElement[bool]:
    """A scoped manager may edit a skill only when every group it is shared with
    is one they manage, and it isn't published org-wide. Delegates to the shared
    read-side helper so this can't drift from the write-side GATE 2. Only group
    rows with a permission count. Every direct user share must also go to a
    member of a managed group."""
    managed = scoped_group_ids_subquery(user)
    share_outside_scope = (
        select(Plugin__User.plugin_id)
        .where(
            Plugin__User.plugin_id == Skill.id,
            Plugin__User.user_id.notin_(managed_group_member_ids_subquery(user)),
        )
        .exists()
    )
    return and_(
        within_managed_scope_clause(
            resource_id_col=Skill.id,
            junction_resource_col=Plugin__UserGroup.plugin_id,
            junction_group_col=Plugin__UserGroup.user_group_id,
            non_public_clause=and_(Skill.built_in_skill_id.is_(None), ~_is_published()),
            managed_subq=managed,
            junction_live_clause=Plugin__UserGroup.permission.is_not(None),
        ),
        ~share_outside_scope,
    )


def skill_visible_to_user(user: User) -> ColumnElement[bool]:
    """Custom skills follow the plugin rule (``onyx.db.plugin_access``).
    Built-in skills have no plugin and keep their own rows."""
    return or_(
        and_(
            Skill.built_in_skill_id.isnot(None),
            or_(
                Skill.public_permission.isnot(None),
                _is_shared_with_user(user),
                _is_shared_with_user_group(user),
            ),
        ),
        _plugin_of_skill_matches(
            lambda plugin, marketplace: plugin_visible_to_user(
                plugin, marketplace, user.id
            )
        ),
    )


def _is_editable_by_user(user: User) -> ColumnElement[bool]:
    """The author, or EDITOR through a user or group share. There is no
    organization-wide edit."""
    editable = _plugin_of_skill_matches(
        lambda plugin, _marketplace: plugin_editable_by_user(plugin, user.id)
    )
    if has_permission(user, Permission.MANAGE_PLUGINS) is PermissionAuthority.SCOPED:
        editable = or_(editable, _is_group_shared_only_within_managed_scope(user))
    return editable


def _runtime_name(user: User) -> ColumnElement[str]:
    """The skill name in the version the user runs. Built-in skills use their
    row name."""
    return func.coalesce(
        _plugin_of_skill(
            lambda plugin, _marketplace: skill_name_in_version(
                version_user_runs(plugin, user.id)
            )
        ).scalar_subquery(),
        Skill.name,
    )


@dataclass(frozen=True)
class _UserSkillSelection:
    """The custom skills one user can see, their choices and the name order
    (``onyx.db.plugin_access``). Only skills that can run take part in the
    name order: valid, and with a ready app if they need one."""

    states: dict[UUID, UserPluginState]
    order: SkillNameOrder

    def enabled(self, skill_id: UUID) -> bool:
        state = self.states.get(skill_id)
        return state is not None and state.enabled and not self.order.hides(skill_id)

    def other_skills_named(self, name: str, skill_id: UUID) -> list[UserPluginState]:
        """Enabled skills other than ``skill_id`` with the name, before the
        name order."""
        return [
            state
            for state in self.states.values()
            if state.plugin_id != skill_id
            and state.enabled
            and name in state.skill_names
        ]


def _user_skill_selection(
    user: User,
    db_session: Session,
    external_app_dependencies: Mapping[UUID, SkillExternalAppDependencyState]
    | None = None,
) -> _UserSkillSelection:
    if external_app_dependencies is None:
        external_app_dependencies = get_skill_external_app_dependencies(
            db_session, user
        )
    states = {
        state.plugin_id: state
        for state in load_user_plugin_states([user.id], db_session)
    }
    can_run = [
        state
        for state in states.values()
        if state.version_is_valid is not False
        and (
            state.plugin_id not in external_app_dependencies
            or external_app_dependencies[state.plugin_id].ready
        )
    ]
    return _UserSkillSelection(
        states=states,
        order=order_skill_names(can_run, reserved_names=BUILT_IN_SKILLS.keys()),
    )


def _exclude_unavailable_built_in_skills[RowT: tuple[Any, ...]](
    stmt: Select[RowT], db_session: Session
) -> Select[RowT]:
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
        if has_global_permission(user, Permission.MANAGE_PLUGINS):
            return stmt
        stmt = stmt.where(skill_visible_to_user(user))
        return _exclude_unavailable_built_in_skills(stmt, db_session)

    if policy == SkillManagementPolicy.EDIT:
        stmt = stmt.where(Skill.built_in_skill_id.is_(None))
        if has_global_permission(user, Permission.MANAGE_PLUGINS):
            return stmt
        return stmt.where(_is_editable_by_user(user))

    raise ValueError(f"Unknown skill management policy: {policy}")


def get_group_ids_for_skill(skill_id: UUID, db_session: Session) -> list[int]:
    """Group ids a skill is shared with — the scope input for GATE 2 checks.
    Only group rows with a permission are shares."""
    return list(
        db_session.scalars(
            select(Plugin__UserGroup.user_group_id).where(
                Plugin__UserGroup.plugin_id == skill_id,
                Plugin__UserGroup.permission.is_not(None),
            )
        )
    )


def affected_user_ids_for_skill(skill: Skill, db_session: Session) -> set[UUID]:
    """Return user IDs with a running sandbox that should contain this skill.

    Deliberately does not filter by user preference: disable/delete flows still
    need previous recipients so the push pipeline can remove the skill files.
    """
    running = select(Sandbox.user_id).where(Sandbox.status == SandboxStatus.RUNNING)
    if not skill.is_custom:
        if skill.public_permission is not None:
            return set(db_session.scalars(running))
        shared_user_ids = select(Skill__User.user_id).where(
            Skill__User.skill_id == skill.id
        )
        shared_group_user_ids = (
            select(User__UserGroup.user_id)
            .join(
                Skill__UserGroup,
                Skill__UserGroup.user_group_id == User__UserGroup.user_group_id,
            )
            .where(Skill__UserGroup.skill_id == skill.id)
        )
        return set(
            db_session.scalars(
                running.where(
                    or_(
                        Sandbox.user_id.in_(shared_user_ids),
                        Sandbox.user_id.in_(shared_group_user_ids),
                    )
                )
            )
        )

    return affected_user_ids_for_plugins([skill.id], db_session)


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
) -> list[RuntimeSkill]:
    """Return the user's effective sandbox skills, each with the plugin version
    the user runs.

    Management visibility, user selection, bundle validity, built-in
    availability, and external-app readiness remain independent inputs. The
    plugin and its version are outer joins, so built-in skills stay.
    """
    external_app_dependencies = get_skill_external_app_dependencies(db_session, user)
    ready_external_app_skill_ids = [
        skill_id
        for skill_id, dependency in external_app_dependencies.items()
        if dependency.ready
    ]
    selection = _user_skill_selection(user, db_session, external_app_dependencies)
    run_plugin: type[Plugin] = aliased(Plugin)
    run_version: type[PluginVersion] = aliased(PluginVersion)
    name = _runtime_name(user)
    stmt = (
        select(
            Skill,
            name,
            run_version.id,
            run_version.bundle_file_id,
            run_version.is_valid,
        )
        .options(
            selectinload(Skill.author),
            selectinload(Skill.user_shares).selectinload(Skill__User.user),
            selectinload(Skill.group_shares).selectinload(Skill__UserGroup.user_group),
        )
        .outerjoin(run_plugin, run_plugin.id == Skill.id)
        .outerjoin(
            run_version, run_version.id == version_user_runs(run_plugin, user.id)
        )
        .order_by(name, Skill.id)
        .where(
            skill_visible_to_user(user),
            or_(
                Skill.built_in_skill_id.isnot(None),
                Skill.id.in_(set(selection.order.kept.values())),
            ),
            or_(
                ~exists().where(ExternalApp__Skill.skill_id == Skill.id),
                Skill.id.in_(ready_external_app_skill_ids),
            ),
            or_(
                Skill.built_in_skill_id.isnot(None),
                and_(run_version.id.isnot(None), run_version.is_valid.is_not(False)),
            ),
        )
    )
    rows = db_session.execute(_exclude_unavailable_built_in_skills(stmt, db_session))
    skills: list[RuntimeSkill] = []
    for skill, skill_name, version_id, bundle_file_id, is_valid in rows:
        state = selection.states.get(skill.id)
        if skill.built_in_skill_id is not None or state is None:
            skills.append(
                RuntimeSkill(
                    skill=skill,
                    name=skill_name,
                    version=None,
                    name_rank=SkillNameRank.BUILT_IN,
                    plugin_created_at=None,
                )
            )
            continue
        skills.append(
            RuntimeSkill(
                skill=skill,
                name=skill_name,
                version=RuntimeSkillVersion(
                    id=version_id, bundle_file_id=bundle_file_id, is_valid=is_valid
                ),
                name_rank=state.name_rank,
                plugin_created_at=state.created_at,
            )
        )
    kept, _hidden = keep_one_skill_per_name(skills)
    return kept


def keep_one_skill_per_name(
    skills: Iterable[RuntimeSkill],
) -> tuple[list[RuntimeSkill], list[RuntimeSkill]]:
    """Apply the name order (``onyx.db.plugin_access``) to runtime skills.
    Returns the kept skills, in input order, and the hidden ones."""
    skills = list(skills)
    winners: dict[str, RuntimeSkill] = {}
    for runtime_skill in sorted(
        skills,
        key=lambda item: skill_name_order_key(
            item.name_rank, item.plugin_created_at, item.skill.id
        ),
    ):
        winners.setdefault(runtime_skill.name, runtime_skill)
    kept = [item for item in skills if winners[item.name] is item]
    hidden = [item for item in skills if winners[item.name] is not item]
    return kept, hidden


def fetch_skill(
    skill_id: UUID,
    *,
    policy: SkillManagementPolicy,
    db_session: Session,
    user: User,
    lock_for_update: bool = False,
    allow_key_share: bool = False,
) -> Skill | None:
    """``allow_key_share`` takes FOR NO KEY UPDATE, so foreign-key checks of
    rows that reference the skill do not wait for this lock."""
    stmt = _skill_select_for_management_policy(
        policy=policy,
        db_session=db_session,
        user=user,
        order_by_name=False,
    ).where(Skill.id == skill_id)
    if lock_for_update:
        stmt = stmt.with_for_update(of=Skill, key_share=allow_key_share)
    return db_session.scalars(stmt).one_or_none()


def add_new_skill__no_commit(
    skill: Skill,
    db_session: Session,
) -> Skill:
    db_session.add(skill)
    db_session.flush()
    return skill


def _lock_user_skill_preferences(user_id: UUID, db_session: Session) -> None:
    """Serialize one user's user_plugin_preference writes on the user row,
    without blocking the foreign-key reads of sharing writes."""
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
    """Enable a newly inserted skill under the same user lock as toggles.
    Refused with 413 when it puts the user past the skill limit."""
    _lock_user_skill_preferences(user_id, db_session)
    user = db_session.get(User, user_id)
    if user is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "User not found.")
    selection = _user_skill_selection(user, db_session)
    state = selection.states.get(skill.id)
    if state is not None:
        if state.installation_policy == PluginInstallationPolicy.REQUIRED:
            return True
        if any(
            selection.other_skills_named(name, skill.id) for name in state.skill_names
        ):
            return False
    if skill.is_custom:
        plugin = lock_skill_plugin__no_commit(skill, db_session)
        with skill_limit_check(
            db_session, [plugin.id], actor_id=user_id, user_ids=[user_id]
        ):
            set_plugin_preferences__no_commit(user_id, [plugin.id], True, db_session)
    _write_legacy_choice__no_commit(user_id, skill, True, db_session)
    return True


def _write_legacy_choice__no_commit(
    user_id: UUID, skill: Skill, enabled: bool, db_session: Session
) -> None:
    """Mirror a choice to the legacy user_skill_preference row. Reads use
    user_plugin_preference. The legacy index uq_user_skill_preference_name
    allows one enabled row per name, and a hidden plugin's kept choice can
    hold that name; the legacy row then keeps its old value."""
    try:
        with db_session.begin_nested():
            db_session.execute(
                insert(UserSkillPreference)
                .values(
                    user_id=user_id, skill_id=skill.id, name=skill.name, enabled=enabled
                )
                .on_conflict_do_update(
                    index_elements=[
                        UserSkillPreference.user_id,
                        UserSkillPreference.skill_id,
                    ],
                    set_={"enabled": enabled},
                )
            )
    except IntegrityError as exc:
        if not is_unique_violation(exc, "uq_user_skill_preference_name"):
            raise


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
    created_public = external_app_id is not None
    with skill_limit_check(db_session, actor_id=user.id) as limit_check:
        return _create_custom_skill__no_commit(
            ingested,
            user,
            db_session,
            created_public=created_public,
            change=change,
            external_app_id=external_app_id,
            limit_check=limit_check,
        )


def _create_custom_skill__no_commit(
    ingested: IngestedBundle,
    user: User,
    db_session: Session,
    *,
    created_public: bool,
    change: "SkillSharingChange | None",
    external_app_id: int | None,
    limit_check: SkillLimitCheck,
) -> tuple[Skill, set[UUID]]:
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
    limit_check.track_new([skill.id])
    if external_app_id is not None:
        associate_custom_skill_with_external_app__no_commit(
            db_session,
            external_app_id=external_app_id,
            skill_id=skill.id,
        )
    affected: set[UUID] = set()
    if change is not None:
        # main allows two published skills with one name, so a new skill that
        # is published takes the next free name.
        affected = share_skill__no_commit(
            skill, change, user, db_session, on_name_clash="rename"
        )
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
) -> AddedPluginVersion | None:
    """Add a plugin version with the new bundle and keep the legacy skill row
    current. The caller holds the skill row lock (``lock_for_update``) and
    deletes the pruned bundles after the commit.

    Returns None, and changes nothing, when ``skip_if_unchanged`` is set and
    the files did not change; the caller then deletes the new blob. A version
    that puts a user who runs it past the skill limit is refused with 413.

    Rejects built-in rows — they have no bundle.
    """
    if not skill.is_custom:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Skill '{skill.name}' is a built-in and has no bundle.",
        )

    # A skill with no plugin gets one copied from its legacy row first, so the
    # change below is version 2, as for every other skill.
    plugin = lock_skill_plugin__no_commit(skill, db_session)
    with skill_limit_check(db_session, [plugin.id], actor_id=user.id):
        added = add_plugin_version__no_commit(
            plugin=plugin,
            content=ingested.content,
            base_version_id=base_version_id,
            created_by=user,
            skip_if_unchanged=skip_if_unchanged,
            previous_manifest=previous_manifest,
            db_session=db_session,
        )
        if added is None:
            return None

        skill.bundle_file_id = ingested.bundle_file_id
        skill.bundle_sha256 = ingested.bundle_sha256
        skill.name = ingested.canonical_name
        skill.description = ingested.description
        skill.is_valid = True
        db_session.flush()
    return added


def _ensure_external_app_skill_stays_public(
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


def _publish_requested(
    skill: Skill,
    public_permission: SkillSharePermission | None,
    db_session: Session,
) -> bool:
    """Check a request for organization access to a custom skill, and return
    whether it publishes. VIEWER publishes. None keeps the skill private and is
    refused for a published skill, because publishing is one-way.
    Organization-wide EDITOR is refused; editors are named users and groups. A
    skill linked to an external app stays published."""
    _ensure_external_app_skill_stays_public(skill, public_permission, db_session)
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
        return False
    return True


def set_skill_public_permission(
    *,
    skill: Skill,
    public_permission: SkillSharePermission | None,
    db_session: Session,
) -> None:
    """Publish a custom skill (VIEWER) or keep it private (None), with no
    permission check. Routes use ``share_skill__no_commit``."""
    if not skill.is_custom:
        _ensure_external_app_skill_stays_public(skill, public_permission, db_session)
        skill.public_permission = public_permission
        db_session.flush()
        return
    if _publish_requested(skill, public_permission, db_session):
        apply_plugin_access_change__no_commit(
            [skill.id], PluginAccessChange(publish=True), None, db_session
        ).raise_first_failure()


def skill_user_states(
    user: User,
    skill_ids: Iterable[UUID],
    db_session: Session,
) -> dict[UUID, SkillUserState]:
    requested_ids = set(skill_ids)
    if not requested_ids:
        return {}

    external_app_dependencies = get_skill_external_app_dependencies(db_session, user)
    selection = _user_skill_selection(user, db_session, external_app_dependencies)
    hidden = {entry.plugin_id: entry for entry in selection.order.hidden}
    states: dict[UUID, SkillUserState] = {}
    for skill_id, built_in_skill_id in db_session.execute(
        select(Skill.id, Skill.built_in_skill_id).where(Skill.id.in_(requested_ids))
    ):
        if built_in_skill_id is not None:
            states[skill_id] = SkillUserState(
                enabled=True,
                can_toggle=False,
                installation_policy=None,
                external_app_dependency=external_app_dependencies.get(skill_id),
                name_hidden=None,
            )
            continue
        state = selection.states.get(skill_id)
        enabled = selection.enabled(skill_id)
        states[skill_id] = SkillUserState(
            enabled=enabled,
            installation_policy=state.installation_policy
            if state is not None
            else None,
            can_toggle=state is not None
            and state.version_is_valid is not False
            and state.installation_policy != PluginInstallationPolicy.REQUIRED
            and (
                enabled
                or skill_id not in external_app_dependencies
                or external_app_dependencies[skill_id].ready
            ),
            external_app_dependency=external_app_dependencies.get(skill_id),
            name_hidden=hidden.get(skill_id),
        )
    return states


def set_skill_enabled_for_user(
    *,
    skill_id: UUID,
    enabled: bool,
    replace_conflict: bool = False,
    user: User,
    db_session: Session,
) -> Skill:
    _lock_user_skill_preferences(user.id, db_session)
    # Another user's switch inserts a preference for this skill while it holds
    # a plugin lock this call waits for. A FOR UPDATE here blocks that
    # foreign-key check and the two switches deadlock.
    skill = fetch_skill(
        skill_id,
        policy=SkillManagementPolicy.VIEW,
        user=user,
        db_session=db_session,
        lock_for_update=True,
        allow_key_share=True,
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
        selection = _user_skill_selection(user, db_session)
        target = selection.states.get(skill.id)
        skill_name = (
            target.skill_names[0] if target and target.skill_names else skill.name
        )
        # Only skills the user can see conflict. A hidden plugin's kept choice
        # neither blocks the switch nor changes.
        others = selection.other_skills_named(skill_name, skill.id)
        if any(
            other.installation_policy == PluginInstallationPolicy.REQUIRED
            for other in others
        ):
            raise OnyxError(
                OnyxErrorCode.SKILL_NAME_CONFLICT,
                "A required skill already uses this name.",
            )
        conflicts = sorted({other.plugin_id for other in others})
        if conflicts and not replace_conflict:
            raise OnyxError(
                OnyxErrorCode.SKILL_NAME_CONFLICT,
                f"Another skill named '{skill_name}' is already enabled.",
            )
    # One id order for the target and its conflicts, so two users who switch
    # between the same skills cannot deadlock on the plugin rows.
    locked_plugin_ids = _lock_custom_skill_plugins([skill.id, *conflicts], db_session)
    conflict_plugin_ids = [
        plugin_id for plugin_id in locked_plugin_ids if plugin_id != skill.id
    ]
    with skill_limit_check(
        db_session, locked_plugin_ids, actor_id=user.id, user_ids=[user.id]
    ):
        if conflicts:
            set_plugin_preferences__no_commit(
                user.id, conflict_plugin_ids, False, db_session
            )
            for conflict in db_session.scalars(
                select(Skill).where(Skill.id.in_(conflicts)).order_by(Skill.id)
            ):
                _write_legacy_choice__no_commit(user.id, conflict, False, db_session)
        set_plugin_preferences__no_commit(user.id, [skill.id], enabled, db_session)
        _write_legacy_choice__no_commit(user.id, skill, enabled, db_session)
    return skill


def connect_external_app_within_skill_limit__no_commit(
    external_app_id: int,
    user: User,
    connect: Callable[[], object],
    db_session: Session,
) -> list[UUID]:
    """Run ``connect``, which stores the user's app credentials, and keep it.
    When the app's skills would put the user past the skill limit, leave off
    the ones that do not fit, in name order, with a saved "off" choice, and
    return their ids. Turning one on later runs the limit check again. A
    Required skill cannot be left off; the run-time rule applies to it."""
    _lock_user_skill_preferences(user.id, db_session)
    plugin_ids = _lock_custom_skill_plugins(
        db_session.scalars(
            select(ExternalApp__Skill.skill_id).where(
                ExternalApp__Skill.external_app_id == external_app_id
            )
        ),
        db_session,
    )
    check = SkillLimitCheck(db_session, user.id, [user.id])
    check.track(plugin_ids)
    connect()
    outcome = check.measure()
    total = outcome.users_over.get(user.id)
    if total is None:
        return []
    app_usage = plugin_usage_by_plugin(user.id, plugin_ids, db_session)
    states = {
        state.plugin_id: state
        for state in load_user_plugin_states([user.id], db_session, plugin_ids)
    }
    kept = total
    for usage in app_usage.values():
        kept -= usage
    left_off: list[UUID] = []
    for plugin_id in sorted(
        app_usage, key=lambda plugin_id: (states[plugin_id].skill_names, plugin_id)
    ):
        usage = app_usage[plugin_id]
        required = (
            states[plugin_id].installation_policy == PluginInstallationPolicy.REQUIRED
        )
        if (kept + usage).is_over_write_limit and not required:
            left_off.append(plugin_id)
        else:
            kept += usage
    if left_off:
        set_plugin_preferences__no_commit(user.id, left_off, False, db_session)
        for skill in db_session.scalars(
            select(Skill).where(Skill.id.in_(left_off)).order_by(Skill.id)
        ):
            _write_legacy_choice__no_commit(user.id, skill, False, db_session)
    return left_off


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
    """Set the company install setting of a custom skill, with no permission
    check. Routes use ``share_skill__no_commit``."""
    if not skill.is_custom:
        if policy != SkillInstallationPolicy.AVAILABLE:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Installation policies apply only to custom skills.",
            )
        return
    apply_plugin_access_change__no_commit(
        [skill.id],
        PluginAccessChange(
            company_installation_policy=plugin_installation_policy(policy)
        ),
        None,
        db_session,
    ).raise_first_failure()


def replace_skill_shares(
    *,
    skill: Skill,
    db_session: Session,
    user_shares: Mapping[UUID, SkillSharePermission] | None = None,
    group_shares: Mapping[int, SkillSharePermission] | None = None,
) -> None:
    """Replace the user or group shares of a custom skill, with no permission
    check. None leaves that kind unchanged. Routes use
    ``share_skill__no_commit``."""
    apply_plugin_access_change__no_commit(
        [skill.id],
        PluginAccessChange(
            user_grants=_user_grants(user_shares),
            group_grants=_group_grants(group_shares),
        ),
        None,
        db_session,
    ).raise_first_failure()


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
    with skill_limit_check(db_session, [plugin.id], actor_id=None):
        _transfer_skill_plugin__no_commit(
            skill, plugin, previous_owner_user_id, new_owner_user_id, db_session
        )


def _transfer_skill_plugin__no_commit(
    skill: Skill,
    plugin: Plugin,
    previous_owner_user_id: UUID | None,
    new_owner_user_id: UUID,
    db_session: Session,
) -> None:
    try:
        skill.author_user_id = new_owner_user_id
        db_session.flush()
    except IntegrityError as e:
        if is_fk_violation(e):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "New owner user does not exist.",
            ) from e
        raise
    transfer_plugin__no_commit(plugin.id, new_owner_user_id, db_session)
    # The author has no share, so the new owner's share goes.
    apply_plugin_access_change__no_commit(
        [plugin.id],
        PluginAccessChange(
            user_grants=(
                (
                    PluginUserGrant(
                        user_id=previous_owner_user_id,
                        permission=SkillSharePermission.EDITOR,
                    ),
                )
                if previous_owner_user_id is not None
                else ()
            ),
            mode=PluginAccessMode.ADD_ONLY,
        ),
        None,
        db_session,
    ).raise_first_failure()


def delete_skill(skill: Skill, db_session: Session) -> list[str]:
    """Hard-delete a skill and its plugin, and return every bundle file of the
    skill and its versions for caller cleanup. The caller holds the skill row
    lock."""
    bundle_file_ids: set[str] = set()
    if skill.is_custom:
        # A skill with no plugin gets one first, so its bundle is found.
        lock_skill_plugin__no_commit(skill, db_session)
        bundle_file_ids.update(delete_plugin__no_commit(skill.id, db_session))
    if skill.bundle_file_id is not None:
        bundle_file_ids.add(skill.bundle_file_id)
    db_session.delete(skill)
    db_session.flush()
    return sorted(bundle_file_ids)


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
    """A partial update to a skill's access, as the skills API sends it. None
    shares leave that kind unchanged; set_public_permission marks
    public_permission as supplied. ``installation_policy``: UNSET keeps it,
    None means "use the marketplace default", and a value sets that value."""

    public_permission: SkillSharePermission | None = None
    set_public_permission: bool = False
    installation_policy: PluginInstallationPolicy | None | UnsetType = UNSET
    user_shares: Mapping[UUID, SkillSharePermission] | None = None
    group_shares: Mapping[int, SkillSharePermission] | None = None
    # Group install settings for groups in ``group_shares``. A group left out
    # keeps its setting; None removes it.
    group_installation_policies: Mapping[int, PluginInstallationPolicy | None] = field(
        default_factory=dict
    )
    # Group install settings with no change to the share. None removes one.
    group_settings: Mapping[int, PluginInstallationPolicy | None] | None = None


SkillBulkAction = Literal["enable", "disable", "delete"]


def ensure_can_edit_org_visibility(skill: Skill, user: User) -> None:
    if skill.author_user_id == user.id:
        return
    if has_global_permission(user, Permission.MANAGE_PLUGINS):
        return
    raise OnyxError(
        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
        "You do not have permission to change organization-wide skill access.",
    )


def _user_grants(
    shares: Mapping[UUID, SkillSharePermission] | None,
) -> tuple[PluginUserGrant, ...] | None:
    if shares is None:
        return None
    return tuple(
        PluginUserGrant(user_id=user_id, permission=permission)
        for user_id, permission in shares.items()
    )


def _group_grants(
    shares: Mapping[int, SkillSharePermission] | None,
    policies: Mapping[int, PluginInstallationPolicy | None] | None = None,
) -> tuple[PluginGroupGrant, ...] | None:
    if shares is None:
        return None
    policies = policies or {}
    return tuple(
        PluginGroupGrant(
            group_id=group_id,
            permission=permission,
            installation_policy=(policies[group_id] if group_id in policies else UNSET),
        )
        for group_id, permission in shares.items()
    )


def _plugin_access_change(
    change: SkillSharingChange,
    mode: PluginAccessMode,
    on_name_clash: NameClashAction = "raise",
) -> PluginAccessChange:
    """The plugin change for a skills API change. Organization access is
    checked per skill (``_publish_requested``); VIEWER publishes."""
    return PluginAccessChange(
        user_grants=_user_grants(change.user_shares),
        group_grants=_group_grants(
            change.group_shares, change.group_installation_policies
        ),
        group_settings=(
            tuple(
                PluginGroupSetting(group_id=group_id, installation_policy=policy)
                for group_id, policy in change.group_settings.items()
            )
            if change.group_settings is not None
            else None
        ),
        publish=change.set_public_permission
        and change.public_permission == SkillSharePermission.VIEWER,
        company_installation_policy=change.installation_policy,
        mode=mode,
        on_name_clash=on_name_clash,
    )


def _check_skill_access_change(
    skill: Skill, change: SkillSharingChange, user: User, db_session: Session
) -> None:
    if change.set_public_permission:
        ensure_can_edit_org_visibility(skill, user)
        _publish_requested(skill, change.public_permission, db_session)


def publish_skill__no_commit(
    skill: Skill,
    base_version_id: UUID | None,
    user: User,
    db_session: Session,
) -> set[UUID]:
    """Publish the current version of a skill: a first publish for a private
    skill, a publish update for a published one. Only the author or an
    organization-wide manager publishes. Under the Publishing setting this can
    make a review request instead, or be refused. The caller holds the skill
    row lock. Returns the affected users."""
    ensure_can_edit_org_visibility(skill, user)
    plugin = lock_skill_plugin__no_commit(skill, db_session)
    check_base_version(plugin, base_version_id)
    if plugin.published_version_id == plugin.current_version_id:
        return set()
    with skill_limit_check(db_session, [plugin.id], actor_id=user.id):
        before = affected_user_ids_for_plugins([plugin.id], db_session)
        publish_or_request_review__no_commit(
            plugin, skill, plugin.current_version_id, user, "raise", db_session
        )
    return before | affected_user_ids_for_plugins([plugin.id], db_session)


def approve_skill_review__no_commit(
    skill: Skill, version_id: UUID, db_session: Session
) -> set[UUID]:
    """Publish the pending version of a skill. A first publish moves the skill
    to the Organization library, and a name clash there is refused with
    CONFLICT, and a version that puts users past the skill limit with 413
    (R12). The caller holds the skill row lock. Returns the affected users."""
    plugin = lock_skill_plugin__no_commit(skill, db_session)
    version = pending_version(plugin, version_id, db_session)
    with skill_limit_check(db_session, [plugin.id], actor_id=None):
        before = affected_user_ids_for_plugins([plugin.id], db_session)
        publish_or_request_review__no_commit(
            plugin, skill, version.id, None, "raise", db_session
        )
    return before | affected_user_ids_for_plugins([plugin.id], db_session)


def deny_skill_review__no_commit(
    skill: Skill, version_id: UUID, db_session: Session
) -> None:
    """The caller holds the skill row lock."""
    deny_review__no_commit(
        lock_skill_plugin__no_commit(skill, db_session), version_id, db_session
    )


def share_skill__no_commit(
    skill: Skill,
    change: SkillSharingChange,
    user: User,
    db_session: Session,
    on_name_clash: NameClashAction = "raise",
) -> set[UUID]:
    """Apply an access change to one skill through its plugin and return
    every user whose sandbox is affected, before or after the change. Supplied
    user and group shares replace the current ones."""
    _check_skill_access_change(skill, change, user, db_session)
    result = apply_plugin_access_change__no_commit(
        [skill.id],
        _plugin_access_change(change, PluginAccessMode.REPLACE, on_name_clash),
        user,
        db_session,
    )
    result.raise_first_failure()
    return result.affected_user_ids


@dataclass(frozen=True)
class SkillBulkShareResult:
    succeeded: list[UUID]
    # Skill id and the reason, in skill id order.
    failed: list[tuple[UUID, str]]
    affected_user_ids: set[UUID]


def bulk_share_skills__no_commit(
    skill_ids: Iterable[UUID],
    change: SkillSharingChange,
    user: User,
    db_session: Session,
) -> SkillBulkShareResult:
    """Apply one access change to many skills through their plugins. Shares
    are add-only. A skill the user cannot edit, or whose change is refused or
    fails, is reported and changes nothing; the other skills still change. A
    refusal for the whole set fails every skill."""
    failed: dict[UUID, str] = {}
    candidates: list[UUID] = []
    for skill_id in sorted(set(skill_ids)):
        skill = fetch_skill(
            skill_id,
            policy=SkillManagementPolicy.EDIT,
            user=user,
            db_session=db_session,
            lock_for_update=True,
        )
        if skill is None:
            failed[skill_id] = "Skill not found"
            continue
        try:
            _check_skill_access_change(skill, change, user, db_session)
        except OnyxError as exc:
            failed[skill_id] = exc.detail
            continue
        candidates.append(skill_id)

    affected: set[UUID] = set()
    if candidates:
        try:
            with db_session.begin_nested():
                result = apply_plugin_access_change__no_commit(
                    candidates,
                    _plugin_access_change(change, PluginAccessMode.ADD_ONLY),
                    user,
                    db_session,
                )
        except OnyxError as exc:
            failed |= dict.fromkeys(candidates, exc.detail)
        else:
            failed |= {
                skill_id: exc.detail for skill_id, exc in result.failures.items()
            }
            affected = result.affected_user_ids
    return SkillBulkShareResult(
        succeeded=[skill_id for skill_id in candidates if skill_id not in failed],
        failed=sorted(failed.items()),
        affected_user_ids=affected,
    )


def _is_required_for_anyone(skill_id: UUID, db_session: Session) -> bool:
    """The company setting (own, else the marketplace default) or a group
    setting of the skill's plugin is REQUIRED."""
    required = PluginInstallationPolicy.REQUIRED
    return bool(
        db_session.scalar(
            select(
                or_(
                    exists().where(
                        Plugin.id == skill_id,
                        Marketplace.id == Plugin.marketplace_id,
                        func.coalesce(
                            Plugin.installation_policy,
                            Marketplace.default_installation_policy,
                        )
                        == required,
                    ),
                    exists().where(
                        Plugin__UserGroup.plugin_id == skill_id,
                        Plugin__UserGroup.installation_policy == required,
                    ),
                )
            )
        )
    )


def delete_skill_for_user__no_commit(
    skill: Skill, user: User, db_session: Session
) -> tuple[set[UUID], list[str]]:
    """Delete a skill the user may edit. Only a user with organization-wide
    MANAGE_PLUGINS can delete a published skill. Returns the affected users and
    the bundle file ids for caller cleanup."""
    if skill.public_permission is not None and not has_global_permission(
        user, Permission.MANAGE_PLUGINS
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "This skill is published to the organization. Only an admin can delete it.",
        )
    if not has_global_permission(
        user, Permission.MANAGE_PLUGINS
    ) and _is_required_for_anyone(skill.id, db_session):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Only an organization-wide skill manager can delete a required skill.",
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
    with (
        db_session.begin_nested(),
        skill_limit_check(db_session, actor_id=user.id),
    ):
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
    user: User,
    db_session: Session,
) -> tuple[set[UUID], list[str]]:
    """Apply one bulk enable, disable or delete to one skill inside a
    savepoint, so a failure rolls back this skill only. Returns the affected
    users and, for a delete, the bundle file ids for caller cleanup. Bulk
    sharing uses ``bulk_share_skills__no_commit``."""
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
