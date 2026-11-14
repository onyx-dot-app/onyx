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

from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    ColumnElement,
    Row,
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
from sqlalchemy.orm import Session, aliased, selectinload
from sqlalchemy.sql.elements import KeyedColumnElement

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
from onyx.db.external_app_readiness import waits_for_app
from onyx.db.models import (
    ExternalApp__Skill,
    Marketplace,
    Plugin,
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
    get_plugin_version,
    lock_skill_plugin__no_commit,
    plugin_installation_policy,
    publish_or_request_review__no_commit,
    set_plugin_preferences__no_commit,
    transfer_plugin__no_commit,
)
from onyx.db.plugin_access import (
    UserPluginState,
    affected_user_ids_for_plugins,
    frontmatter_in_version,
    load_user_plugin_states,
    order_skill_names,
    plugin_editable_by_user,
    plugin_in_managed_scope,
    plugin_required_for_anyone,
    visible_plugin_ids,
)
from onyx.db.skill_limit import check_skill_limit, lock_user_skill_preferences
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
from onyx.skills.models import PluginFileEntry, SkillUsage


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
    version: RuntimeSkillVersion | None = None
    # Recorded size of the version; None for a built-in or a version with no
    # recorded size.
    usage: SkillUsage | None = None


@dataclass(frozen=True)
class SkillUserState:
    enabled: bool
    can_toggle: bool
    external_app_dependency: SkillExternalAppDependencyState | None
    # The install setting for this user is REQUIRED (company or group).
    required: bool = False


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
        and_(
            Skill.built_in_skill_id.is_(None),
            Skill.id.in_(visible_plugin_ids(user.id)),
        ),
    )


def _is_editable_by_user(user: User) -> ColumnElement[bool]:
    """The author, or EDITOR through a user or group share. There is no
    organization-wide edit."""
    editable = _plugin_of_skill_matches(
        lambda plugin, _marketplace: plugin_editable_by_user(plugin, user.id)
    )
    if has_permission(user, Permission.MANAGE_PLUGINS) is PermissionAuthority.SCOPED:
        editable = or_(
            editable,
            _plugin_of_skill_matches(
                lambda plugin, marketplace: plugin_in_managed_scope(
                    plugin, marketplace, user
                )
            ),
        )
    return editable


class _UserSkillSelection(BaseModel):
    """The custom skills one user can see, their choices and the name order
    (``onyx.db.plugin_access``). Only skills that can run take part in the
    name order, with the names of the user's built-in skills reserved."""

    model_config = ConfigDict(frozen=True)

    states: dict[UUID, UserPluginState]
    # Plugins that lose a skill name (``order_skill_names``).
    hidden: frozenset[UUID]

    def enabled(self, skill_id: UUID) -> bool:
        state = self.states.get(skill_id)
        return state is not None and state.enabled and skill_id not in self.hidden

    def loaded(self) -> list[UserPluginState]:
        """The plugins the sandbox gets: they can run, have a skill and lose
        no name."""
        return [
            state
            for state in self.states.values()
            if state.can_run
            and state.skill_names
            and state.plugin_id not in self.hidden
        ]

    def other_skills_named(
        self, names: Collection[str], skill_id: UUID
    ) -> list[UserPluginState]:
        """Skills other than ``skill_id`` that can run and hold one of the
        names: the ones that take part in the name order."""
        return [
            state
            for state in self.states.values()
            if state.plugin_id != skill_id
            and state.can_run
            and not set(names).isdisjoint(state.skill_names)
        ]


def _user_skill_selection(
    user: User,
    db_session: Session,
    built_in_skills: Iterable[Skill] | None = None,
    left_out: Collection[UUID] = (),
) -> _UserSkillSelection:
    """``left_out``: plugins that cannot run, such as versions the push just
    found invalid."""
    if built_in_skills is None:
        built_in_skills = _runtime_built_in_skills(user, db_session)
    states = {
        state.plugin_id: (
            state.model_copy(update={"can_run": False})
            if state.plugin_id in left_out
            else state
        )
        for state in load_user_plugin_states([user.id], db_session)
    }
    return _UserSkillSelection(
        states=states,
        hidden=order_skill_names(
            states.values(), reserved_names={skill.name for skill in built_in_skills}
        ),
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


def _runtime_built_in_skills(user: User, db_session: Session) -> list[Skill]:
    """The built-in skills the user gets: visible, available, and with a
    ready app if they need one."""
    rows = list(
        db_session.scalars(
            _exclude_unavailable_built_in_skills(
                select(Skill)
                .where(Skill.built_in_skill_id.isnot(None), skill_visible_to_user(user))
                .order_by(Skill.name, Skill.id),
                db_session,
            )
        )
    )
    apps = get_skill_external_app_dependencies(
        db_session, user, [skill.id for skill in rows]
    )
    return [skill for skill in rows if not waits_for_app(apps.get(skill.id))]


def list_runtime_skills_for_user(
    *,
    db_session: Session,
    user: User,
    left_out: Collection[UUID] = (),
) -> list[RuntimeSkill]:
    """The user's sandbox skills in the run-time keep order: built-ins, then
    the custom skills the name order keeps, by ``UserPluginState.keep_key``.
    Each custom skill has the plugin version the user runs."""
    built_ins = _runtime_built_in_skills(user, db_session)
    selection = _user_skill_selection(user, db_session, built_ins, left_out)
    kept = sorted(selection.loaded(), key=lambda state: state.keep_key)
    skill_rows = {
        skill.id: skill
        for skill in db_session.scalars(
            select(Skill).where(Skill.id.in_([state.plugin_id for state in kept]))
        )
    }
    return [RuntimeSkill(skill=skill, name=skill.name) for skill in built_ins] + [
        RuntimeSkill(
            skill=skill_rows[state.plugin_id],
            name=state.skill_names[0],
            version=RuntimeSkillVersion(
                id=state.version_id,
                bundle_file_id=state.bundle_file_id,
                is_valid=state.version_is_valid,
            ),
            usage=state.usage,
        )
        for state in kept
        if state.plugin_id in skill_rows
    ]


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


def enable_new_skill_if_name_available__no_commit(
    skill: Skill,
    user_id: UUID,
    db_session: Session,
) -> bool:
    """Enable a newly inserted skill under the same user lock as toggles.
    Refused with 413 when it puts the user past the skill limit."""
    lock_user_skill_preferences(user_id, db_session)
    user = db_session.get(User, user_id)
    if user is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "User not found.")
    selection = _user_skill_selection(user, db_session)
    state = selection.states.get(skill.id)
    if state is not None:
        if state.installation_policy == PluginInstallationPolicy.REQUIRED:
            return True
        if selection.other_skills_named(state.skill_names, skill.id):
            return False
    if skill.is_custom:
        plugin = lock_skill_plugin__no_commit(skill, db_session)
        with check_skill_limit(db_session, [plugin.id], user_id):
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
    skill_id = uuid4()
    with check_skill_limit(db_session, [skill_id], user.id):
        skill = add_new_skill__no_commit(
            Skill(
                id=skill_id,
                name=ingested.canonical_name,
                description=ingested.description,
                bundle_file_id=ingested.bundle_file_id,
                bundle_sha256=ingested.bundle_sha256,
                is_valid=True,
                author_user_id=user.id,
                public_permission=(
                    SkillSharePermission.VIEWER if created_public else None
                ),
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
        # Inside the check: publishing can turn the skill on for its author.
        if change is not None:
            # main allows two published skills with one name, so a new skill that
            # is published takes the next free name.
            affected = share_skill__no_commit(
                skill, change, user, db_session, on_name_clash="rename"
            )
    return skill, affected


def lock_skill_for_save(skill: Skill, user: User, db_session: Session) -> None:
    """Take the save locks in the toggle's order, the user's lock and then the
    skill row, and check that the user may still edit the skill: the edit
    check before the locks can be stale by now. 404 otherwise."""
    lock_user_skill_preferences(user.id, db_session)
    if (
        fetch_skill(
            skill.id,
            policy=SkillManagementPolicy.EDIT,
            user=user,
            db_session=db_session,
            lock_for_update=True,
        )
        is None
    ):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    db_session.refresh(skill)


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
    current. Takes the save locks (``lock_skill_for_save``) itself, so the
    caller can ingest the bundle without holding them.

    Returns None, and changes nothing, when ``skip_if_unchanged`` is set and
    the files did not change; the caller then deletes the new blob. The
    previous bundle stays: older versions still point at it. A version that
    puts the acting user past the skill limit is refused with 413.

    Rejects built-in rows — they have no bundle.
    """
    if not skill.is_custom:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Skill '{skill.name}' is a built-in and has no bundle.",
        )

    lock_skill_for_save(skill, user, db_session)
    # A skill with no plugin gets one copied from its legacy row first, so the
    # change below is version 2, as for every other skill.
    plugin = lock_skill_plugin__no_commit(skill, db_session)
    with check_skill_limit(db_session, [plugin.id], user.id):
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
    selection: _UserSkillSelection | None = None,
) -> dict[UUID, SkillUserState]:
    requested_ids = set(skill_ids)
    if not requested_ids:
        return {}

    external_app_dependencies = get_skill_external_app_dependencies(db_session, user)
    if selection is None:
        selection = _user_skill_selection(user, db_session)
    states: dict[UUID, SkillUserState] = {}
    for skill_id, built_in_skill_id in db_session.execute(
        select(Skill.id, Skill.built_in_skill_id).where(Skill.id.in_(requested_ids))
    ):
        if built_in_skill_id is not None:
            states[skill_id] = SkillUserState(
                enabled=True,
                can_toggle=False,
                external_app_dependency=external_app_dependencies.get(skill_id),
            )
            continue
        state = selection.states.get(skill_id)
        enabled = selection.enabled(skill_id)
        states[skill_id] = SkillUserState(
            enabled=enabled,
            can_toggle=state is not None
            and state.version_is_valid is not False
            and state.installation_policy != PluginInstallationPolicy.REQUIRED
            and (enabled or not waits_for_app(external_app_dependencies.get(skill_id))),
            external_app_dependency=external_app_dependencies.get(skill_id),
            required=state is not None
            and state.installation_policy == PluginInstallationPolicy.REQUIRED,
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
    lock_user_skill_preferences(user.id, db_session)
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

    selection = _user_skill_selection(user, db_session)
    state = skill_user_states(user, [skill.id], db_session, selection)[skill.id]
    if not state.can_toggle:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "This skill cannot be enabled or disabled.",
        )

    conflicts: list[UUID] = []
    if enabled:
        target = selection.states.get(skill.id)
        names = target.skill_names if target and target.skill_names else (skill.name,)
        # Only skills the user can see conflict. A hidden plugin's kept choice
        # neither blocks the switch nor changes.
        others = selection.other_skills_named(names, skill.id)
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
                f"Another skill named '{names[0]}' is already enabled.",
            )
    # One id order for the target and its conflicts, so two users who switch
    # between the same skills cannot deadlock on the plugin rows.
    locked_plugin_ids = _lock_custom_skill_plugins([skill.id, *conflicts], db_session)
    conflict_plugin_ids = [
        plugin_id for plugin_id in locked_plugin_ids if plugin_id != skill.id
    ]
    with check_skill_limit(db_session, locked_plugin_ids, user.id):
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


def _lock_custom_skill_plugins(
    skill_ids: Iterable[UUID], db_session: Session
) -> list[UUID]:
    """Lock the custom skills among ``skill_ids``, then their plugins, each in
    id order, and return the plugin ids. Built-in skills have no plugin.

    The skill rows take FOR KEY SHARE, the lock the legacy choice write takes
    later. Taken before the plugin rows, it waits for an admin change that
    holds the skill row and wants the plugin row, instead of a deadlock."""
    ids = set(skill_ids)
    if not ids:
        return []
    skills = db_session.scalars(
        select(Skill)
        .where(Skill.id.in_(ids), Skill.built_in_skill_id.is_(None))
        .order_by(Skill.id)
        .with_for_update(of=Skill, read=True, key_share=True)
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
        bundle_file_ids.update(
            file_id
            for file_id in db_session.scalars(
                select(PluginVersion.bundle_file_id).where(
                    PluginVersion.plugin_id == skill.id
                )
            )
            if file_id is not None
        )
        # Cascades to its versions, skills, shares and choices.
        db_session.execute(delete(Plugin).where(Plugin.id == skill.id))
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
            # The plugin's unclassified versions that hold this bundle.
            if validity_update.bundle_file_id is not None:
                db_session.execute(
                    update(PluginVersion)
                    .where(
                        PluginVersion.plugin_id == validity_update.skill_id,
                        PluginVersion.bundle_file_id == validity_update.bundle_file_id,
                        PluginVersion.is_valid.is_(None),
                    )
                    .values(is_valid=validity_update.is_valid)
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
) -> tuple[PluginGroupGrant, ...] | None:
    if shares is None:
        return None
    return tuple(
        PluginGroupGrant(group_id=group_id, permission=permission)
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
        group_grants=_group_grants(change.group_shares),
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
    before = affected_user_ids_for_plugins([plugin.id], db_session)
    publish_or_request_review__no_commit(
        plugin, skill, plugin.current_version_id, user, "raise", db_session
    )
    return before | affected_user_ids_for_plugins([plugin.id], db_session)


def _lock_pending_plugin(skill: Skill, version_id: UUID, db_session: Session) -> Plugin:
    """Lock the plugin of a skill whose pending request is ``version_id``."""
    plugin = lock_skill_plugin__no_commit(skill, db_session)
    get_plugin_version(plugin.id, version_id, db_session)
    if plugin.pending_version_id != version_id:
        raise OnyxError(
            OnyxErrorCode.CONFLICT, "This version has no pending publish request."
        )
    return plugin


def approve_skill_review__no_commit(
    skill: Skill, version_id: UUID, db_session: Session
) -> set[UUID]:
    """Publish the pending version of a skill. A first publish moves the skill
    to the Organization library, and a name clash there is refused with
    CONFLICT. The caller holds the skill row lock. Returns the affected
    users."""
    plugin = _lock_pending_plugin(skill, version_id, db_session)
    before = affected_user_ids_for_plugins([plugin.id], db_session)
    publish_or_request_review__no_commit(
        plugin, skill, version_id, None, "raise", db_session
    )
    return before | affected_user_ids_for_plugins([plugin.id], db_session)


def deny_skill_review__no_commit(
    skill: Skill, version_id: UUID, db_session: Session
) -> None:
    """Clear the pending request. The caller holds the skill row lock."""
    _lock_pending_plugin(skill, version_id, db_session).pending_version_id = None
    db_session.flush()


def list_review_requests(db_session: Session) -> Sequence[Row[Any]]:
    """Every pending request, oldest version first. Labels match the fields of
    ``SkillReviewRequestResponse``."""
    pending: type[PluginVersion] = aliased(PluginVersion)
    published: type[PluginVersion] = aliased(PluginVersion)
    author_email: KeyedColumnElement[str] = User.__table__.c.email
    return db_session.execute(
        select(
            Plugin.id.label("skill_id"),
            frontmatter_in_version("name", pending.id.expression).label("name"),
            pending.id.label("version_id"),
            pending.version_number.label("version_number"),
            published.version_number.label("published_version_number"),
            author_email.label("author_email"),
            pending.created_at.label("version_created_at"),
        )
        .join(pending, pending.id == Plugin.pending_version_id)
        .outerjoin(published, published.id == Plugin.published_version_id)
        .outerjoin(User.__table__, User.__table__.c.id == Plugin.author_user_id)
        .order_by(pending.created_at, pending.id)
    ).all()


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


def may_delete_skill(*, published: bool, required_for_anyone: bool, user: User) -> bool:
    """A user who can edit a skill deletes it, except a published skill or one
    REQUIRED for anyone, which needs organization-wide MANAGE_PLUGINS. The
    delete route and ``SkillResponse.can_delete`` use this one rule."""
    return not (published or required_for_anyone) or has_global_permission(
        user, Permission.MANAGE_PLUGINS
    )


def delete_skill_for_user__no_commit(
    skill: Skill, user: User, db_session: Session
) -> tuple[set[UUID], list[str]]:
    """Delete a skill the user may edit. Only a user with organization-wide
    MANAGE_PLUGINS can delete a published skill. Returns the affected users and
    the bundle file ids for caller cleanup."""
    published = skill.public_permission is not None
    required_for_anyone = bool(
        db_session.scalar(
            select(
                exists().where(
                    Plugin.id == skill.id,
                    Marketplace.id == Plugin.marketplace_id,
                    plugin_required_for_anyone(Plugin, Marketplace),
                )
            )
        )
    )
    if not may_delete_skill(
        published=published, required_for_anyone=required_for_anyone, user=user
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "This skill is published to the organization. Only an admin can delete it."
            if published
            else "Only an organization-wide skill manager can delete a required skill.",
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
