"""DB operations for skills.

A built-in skill is a ``skill`` row with ``built_in_skill_id`` set. Every user
gets it, subject to its availability and the app-skill rule
(``onyx.db.app_skill``). A custom skill is a plugin (``onyx.db.plugin``) whose
version holds one skill at the bundle root. Its id is the plugin id. Old custom
``skill`` rows stay in the database for a rollback; no code reads them.

Management authorization:
- ``fetch_skill`` and ``list_skills`` are the view policy: visible plugins,
  and every skill for an organization-wide skill manager.
- ``fetch_editable_skill`` is the mutation policy. It returns only plugins the
  user can modify.

Runtime selection is deliberately separate from authorization. It applies
visibility without an admin bypass, user enablement, validity and built-in
availability.

Access writes (shares, publishing, the install setting) go through
``onyx.db.plugin.apply_plugin_access_change__no_commit``. A bundle change adds
a plugin version and never deletes the previous bundle. Publishing is one-way,
and there is no organization-wide edit.

Mutation helpers do not commit unless their docstring explicitly says otherwise.
Callers normally control the transaction boundary so multi-step operations can
roll back atomically.
"""

from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    ColumnElement,
    Row,
    Select,
    case,
    delete,
    exists,
    or_,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import KeyedColumnElement

from onyx.auth.permissions import has_global_permission, has_permission
from onyx.db.app_skill import built_in_app_skills
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    AccountType,
    MarketplaceKind,
    Permission,
    PermissionAuthority,
    PluginInstallationPolicy,
    SkillSharePermission,
)
from onyx.db.models import (
    Marketplace,
    Plugin,
    Plugin__UserGroup,
    PluginSkill,
    PluginVersion,
    Skill,
    User,
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
    create_plugin__no_commit,
    get_plugin_version,
    is_personal_synced,
    is_skill_version,
    is_synced,
    private_plugins_blocking_user_delete,
    publish_or_request_review__no_commit,
    refuse_if_synced,
    set_plugin_preferences__no_commit,
    transfer_plugin__no_commit,
)
from onyx.db.plugin_access import (
    UserPluginState,
    affected_user_ids_for_plugins,
    frontmatter_in_version,
    holds_one_root_skill,
    load_user_plugin_states,
    order_skill_names,
    plugin_editable_by_user,
    plugin_in_managed_scope,
    plugin_required_for_anyone,
    version_user_runs,
    visible_plugin_ids,
)
from onyx.db.skill_limit import check_skill_limit, lock_user_skill_preferences
from onyx.db.skill_models import PluginRename, PrivatePluginsTransfer
from onyx.db.users import fetch_user_by_id
from onyx.db.utils import UNSET, UnsetType, is_fk_violation
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.built_in import (
    BUILT_IN_SKILLS,
    CHAT_BUILT_IN_SKILL_IDS,
    EXTERNAL_APP_SKILL_ID_TO_APP_TYPE,
    BuiltInSkillDefinition,
)
from onyx.skills.ingest import IngestedBundle
from onyx.skills.models import (
    ChatSkill,
    PluginFileEntry,
    PluginVersionContent,
    SkillUsage,
)

# A built-in skill row, or the plugin of a custom skill.
type StoredSkill = Skill | Plugin


class SkillValidityUpdate(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, arbitrary_types_allowed=True)

    skill_id: UUID
    bundle_file_id: str | None
    is_valid: bool


class RuntimeSkillVersion(BaseModel):
    """The plugin version a user runs (``version_user_runs``)."""

    model_config = ConfigDict(strict=True, frozen=True, arbitrary_types_allowed=True)

    id: UUID
    bundle_file_id: str | None
    is_valid: bool | None


class RuntimeSkillFolder(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)

    path: str
    name: str


class RuntimeSkill(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, arbitrary_types_allowed=True)

    id: UUID
    built_in_skill_id: str | None = None
    name: str
    plugin_skills: tuple[RuntimeSkillFolder, ...] = ()
    # None for a built-in skill.
    version: RuntimeSkillVersion | None = None
    # Recorded size of the version; None for a built-in or a version with no
    # recorded size.
    usage: SkillUsage | None = None
    # The external app whose settings render an app built-in; None otherwise.
    external_app_id: int | None = None


class SkillUserState(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, arbitrary_types_allowed=True)

    enabled: bool
    can_toggle: bool
    # The install setting for this user is REQUIRED (company or group).
    required: bool = False
    # The user turned the skill on, but these skills hold one of its names,
    # so it does not load and shows as off.
    name_held_by: tuple[str, ...] = ()


def is_published(plugin: Plugin, db_session: Session) -> bool:
    """Published means: in the Organization library."""
    return (
        db_session.scalar(
            select(Marketplace.kind).where(Marketplace.id == plugin.marketplace_id)
        )
        == MarketplaceKind.ORGANIZATION_LIBRARY
    )


def _editable_by_user(user: User) -> ColumnElement[bool]:
    """The author, or EDITOR through a user or group share, or a group manager
    for a plugin in their managed scope. There is no organization-wide edit."""
    editable = plugin_editable_by_user(Plugin, user.id)
    if has_permission(user, Permission.MANAGE_PLUGINS) is PermissionAuthority.SCOPED:
        marketplace: type[Marketplace] = aliased(Marketplace)
        editable = or_(
            editable,
            select(marketplace.id)
            .where(
                marketplace.id == Plugin.marketplace_id,
                plugin_in_managed_scope(Plugin, marketplace, user),
            )
            .correlate_except(marketplace)
            .exists(),
        )
    return editable


class _UserSkillSelection(BaseModel):
    """The custom skills one user can see, their choices and the name order
    (``onyx.db.plugin_access``). Only skills that can run take part in the
    name order, with the names of the user's built-in skills reserved."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    states: dict[UUID, UserPluginState]
    # Plugins that lose a skill name (``order_skill_names``).
    hidden: frozenset[UUID]
    built_ins: list[RuntimeSkill]
    built_in_app_skills: dict[str, int]

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
        self, names: Collection[str], skill_id: UUID | None
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
    left_out: Collection[UUID] = (),
) -> _UserSkillSelection:
    """``left_out``: plugins that cannot run, such as versions the push just
    found invalid."""
    states = {
        state.plugin_id: (
            state.model_copy(update={"can_run": False})
            if state.plugin_id in left_out
            else state
        )
        for state in load_user_plugin_states([user.id], db_session)
    }
    app_skills = built_in_app_skills(user.id, db_session)
    built_ins = _runtime_built_in_skills(app_skills, db_session)
    return _UserSkillSelection(
        states=states,
        hidden=order_skill_names(
            states.values(),
            reserved_names={
                name
                for skill in built_ins
                for name in (skill.name, *(f.name for f in skill.plugin_skills))
            },
        ),
        built_ins=built_ins,
        built_in_app_skills=app_skills,
    )


def _built_in_skill_select(
    db_session: Session, *, include_unavailable: bool
) -> Select[tuple[Skill]]:
    """Built-in rows by name. ``include_unavailable`` keeps built-ins whose
    codified ``is_available(db)`` returns False (admins see all rows)."""
    stmt = (
        select(Skill)
        .where(Skill.built_in_skill_id.is_not(None))
        .order_by(Skill.name, Skill.id)
    )
    if include_unavailable:
        return stmt
    unavailable = [
        d.built_in_skill_id
        for d in BUILT_IN_SKILLS.values()
        if not d.is_available(db_session)
    ]
    if not unavailable:
        return stmt
    return stmt.where(Skill.built_in_skill_id.notin_(unavailable))


def _not_others_personal_marketplace(user: User) -> ColumnElement[bool]:
    """A manager reaches every plugin except those of another user's personal
    GitHub marketplace: only its owner gets them."""
    return Plugin.marketplace_id.not_in(
        select(Marketplace.id).where(
            Marketplace.kind == MarketplaceKind.GITHUB,
            Marketplace.owner_user_id.is_not(None),
            Marketplace.owner_user_id != user.id,
        )
    )


def _visible_custom_skill_select(user: User) -> Select[tuple[Plugin]]:
    runs = version_user_runs(Plugin, user.id)
    stmt = select(Plugin)
    if has_global_permission(user, Permission.MANAGE_PLUGINS):
        stmt = stmt.where(_not_others_personal_marketplace(user))
    else:
        stmt = stmt.where(Plugin.id.in_(visible_plugin_ids(user.id)))
    return stmt.order_by(
        case(
            (holds_one_root_skill(runs), frontmatter_in_version("name", runs)),
            else_=Plugin.name,
        ),
        Plugin.id,
    )


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


def list_skills(*, db_session: Session, user: User) -> list[StoredSkill]:
    """The skills the user can view: built-ins, then custom skills, each by
    name."""
    built_ins = db_session.scalars(
        _built_in_skill_select(
            db_session,
            include_unavailable=has_global_permission(user, Permission.MANAGE_PLUGINS),
        )
    ).all()
    customs = db_session.scalars(_visible_custom_skill_select(user)).all()
    return [*built_ins, *customs]


def _built_in_skill_folders(
    definition: BuiltInSkillDefinition,
) -> tuple[RuntimeSkillFolder, ...]:
    if is_skill_version(skill.path for skill in definition.skills):
        return ()
    return tuple(
        RuntimeSkillFolder(path=skill.path, name=skill.name)
        for skill in definition.skills
    )


def _runtime_built_in_skills(
    app_skills: Mapping[str, int], db_session: Session
) -> list[RuntimeSkill]:
    """The available built-in skills. An app built-in only when it is in
    ``app_skills``."""
    runtime: list[RuntimeSkill] = []
    for skill in db_session.scalars(
        _built_in_skill_select(db_session, include_unavailable=False)
    ):
        built_in_skill_id = skill.built_in_skill_id or ""
        if (
            built_in_skill_id in EXTERNAL_APP_SKILL_ID_TO_APP_TYPE
            and built_in_skill_id not in app_skills
        ):
            continue
        definition = BUILT_IN_SKILLS.get(built_in_skill_id)
        runtime.append(
            RuntimeSkill(
                id=skill.id,
                built_in_skill_id=built_in_skill_id,
                name=skill.name,
                plugin_skills=_built_in_skill_folders(definition)
                if definition is not None
                else (),
                external_app_id=app_skills.get(built_in_skill_id),
            )
        )
    return runtime


def list_runtime_skills_for_user(
    *,
    db_session: Session,
    user: User,
    left_out: Collection[UUID] = (),
) -> list[RuntimeSkill]:
    """The user's sandbox skills in the run-time keep order: built-ins, then
    the custom skills the name order keeps, by ``UserPluginState.keep_key``.
    Each custom skill has the plugin version the user runs."""
    selection = _user_skill_selection(user, db_session, left_out)
    kept = sorted(selection.loaded(), key=lambda state: state.keep_key)
    return selection.built_ins + [
        RuntimeSkill(
            id=state.plugin_id,
            name=(
                state.skill_names[0]
                if is_skill_version(state.skill_paths)
                else state.plugin_name
            ),
            plugin_skills=(
                ()
                if is_skill_version(state.skill_paths)
                else tuple(
                    RuntimeSkillFolder(path=path, name=name)
                    for path, name in zip(
                        state.skill_paths, state.skill_names, strict=True
                    )
                )
            ),
            version=RuntimeSkillVersion(
                id=state.version_id,
                bundle_file_id=state.bundle_file_id,
                is_valid=state.version_is_valid,
            ),
            usage=state.usage,
        )
        for state in kept
    ]


def list_chat_built_in_skills(db_session: Session) -> list[RuntimeSkill]:
    """The available built-ins that chat shows and that load_skill copies
    into the VM. They do not depend on the user."""
    return [
        RuntimeSkill(
            id=row.id,
            built_in_skill_id=row.built_in_skill_id,
            name=row.name,
            plugin_skills=_built_in_skill_folders(
                BUILT_IN_SKILLS[row.built_in_skill_id or ""]
            ),
        )
        for row in db_session.scalars(
            _built_in_skill_select(db_session, include_unavailable=False).where(
                Skill.built_in_skill_id.in_(CHAT_BUILT_IN_SKILL_IDS)
            )
        )
    ]


def list_chat_skills(
    db_session: Session, user: User, *, with_sandbox: bool
) -> list[ChatSkill]:
    """Built-ins only ``with_sandbox``: when the turn has the sandbox tools."""
    if user.is_anonymous:
        return []
    skills: list[ChatSkill] = []
    if with_sandbox:
        skills += [
            ChatSkill(
                name=plugin_skill.name if plugin_skill.path else built_in.name,
                description=plugin_skill.description,
                version_id=built_in.id,
                path=plugin_skill.path,
                built_in_skill_id=built_in.built_in_skill_id,
            )
            for built_in in list_chat_built_in_skills(db_session)
            for plugin_skill in BUILT_IN_SKILLS[built_in.built_in_skill_id or ""].skills
        ]
    plugin_by_version = {
        state.version_id: state.plugin_id
        for state in _user_skill_selection(user, db_session).loaded()
    }
    version_ids = list(plugin_by_version)
    if version_ids:
        skills += [
            ChatSkill(
                name=name,
                description=description,
                short_description=short_description,
                version_id=version_id,
                path=path,
                plugin_id=plugin_by_version[version_id],
            )
            for version_id, path, name, description, short_description in (
                db_session.execute(
                    select(
                        PluginSkill.plugin_version_id,
                        PluginSkill.path,
                        PluginSkill.frontmatter["name"].astext,
                        PluginSkill.frontmatter["description"].astext,
                        PluginSkill.frontmatter[
                            ("metadata", "short-description")
                        ].astext,
                    ).where(PluginSkill.plugin_version_id.in_(version_ids))
                )
            )
        ]
    return sorted(skills, key=lambda skill: (skill.name, skill.version_id))


def fetch_skill(
    skill_id: UUID, *, db_session: Session, user: User
) -> StoredSkill | None:
    """The skill when the user can view it. An app built-in shows only to a
    user who gets it."""
    plugin = db_session.scalars(
        _visible_custom_skill_select(user).where(Plugin.id == skill_id)
    ).one_or_none()
    if plugin is not None:
        return plugin
    skill = db_session.scalars(
        _built_in_skill_select(
            db_session,
            include_unavailable=has_global_permission(user, Permission.MANAGE_PLUGINS),
        ).where(Skill.id == skill_id)
    ).one_or_none()
    if (
        skill is not None
        and skill.built_in_skill_id in EXTERNAL_APP_SKILL_ID_TO_APP_TYPE
        and skill.built_in_skill_id not in built_in_app_skills(user.id, db_session)
    ):
        return None
    return skill


def fetch_editable_skill(
    skill_id: UUID,
    *,
    db_session: Session,
    user: User,
    lock_for_update: bool = False,
    any_plugin: bool = False,
) -> Plugin | None:
    """The plugin of a custom skill the user may edit. Built-in skills are
    never editable. ``any_plugin`` also returns a plugin whose current
    version is not a skill, for a change that does not edit the files:
    sharing, publishing, versions and delete."""
    stmt = select(Plugin).where(Plugin.id == skill_id)
    if not any_plugin:
        stmt = stmt.where(holds_one_root_skill(Plugin.current_version_id.expression))
    if has_global_permission(user, Permission.MANAGE_PLUGINS):
        stmt = stmt.where(_not_others_personal_marketplace(user))
    else:
        stmt = stmt.where(_editable_by_user(user))
    if lock_for_update:
        stmt = stmt.with_for_update(of=Plugin).execution_options(populate_existing=True)
    return db_session.scalars(stmt).one_or_none()


def add_new_skill__no_commit(
    skill: Skill,
    db_session: Session,
) -> Skill:
    db_session.add(skill)
    db_session.flush()
    return skill


def enable_new_skill_if_name_available__no_commit(
    plugin: Plugin,
    user_id: UUID,
    db_session: Session,
) -> bool:
    """Enable a new skill under the same user lock as toggles. Refused with
    413 when it puts the user past the skill limit."""
    lock_user_skill_preferences(user_id, db_session)
    user = db_session.get(User, user_id)
    if user is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "User not found.")
    selection = _user_skill_selection(user, db_session)
    state = selection.states.get(plugin.id)
    if state is not None:
        if state.installation_policy == PluginInstallationPolicy.REQUIRED:
            return True
        if selection.other_skills_named(state.skill_names, plugin.id):
            return False
    with check_skill_limit(db_session, user_id):
        set_plugin_preferences__no_commit(user_id, [plugin.id], True, db_session)
    return True


def create_custom_skill__no_commit(
    ingested: IngestedBundle,
    user: User,
    db_session: Session,
    *,
    change: "SkillSharingChange | None" = None,
) -> tuple[Plugin, set[UUID]]:
    """Create a custom skill: its plugin, version 1 and plugin_skill row, in
    the caller's transaction. The skill starts in the author's "My uploads".
    Returns the plugin and the users the access change affects."""
    plugin_id = uuid4()
    with check_skill_limit(db_session, user.id):
        plugin = create_plugin__no_commit(
            plugin_id, ingested.canonical_name, ingested.content, user, db_session
        )
        affected: set[UUID] = set()
        # Inside the check: publishing can turn the skill on for its author.
        if change is not None:
            # A new skill that is published takes the next free name.
            affected = share_skill__no_commit(
                plugin, change, user, db_session, on_name_clash="rename"
            )
    return plugin, affected


def create_uploaded_plugin__no_commit(
    content: PluginVersionContent,
    auto_enable: bool,
    user: User,
    db_session: Session,
) -> tuple[Plugin, bool]:
    if content.manifest is None:
        raise RuntimeError("Bug: an uploaded plugin has a manifest.")
    plugin_id = uuid4()
    with check_skill_limit(db_session, user.id):
        plugin = create_plugin__no_commit(
            plugin_id, content.manifest.name, content, user, db_session
        )
    enabled = auto_enable and enable_new_skill_if_name_available__no_commit(
        plugin, user.id, db_session
    )
    return plugin, enabled


def _add_plugin_version_for_user__no_commit(
    plugin_id: UUID,
    content: PluginVersionContent,
    base_version_id: UUID | None,
    skip_if_unchanged: bool,
    user: User,
    db_session: Session,
) -> tuple[Plugin, PluginVersion | None]:
    lock_user_skill_preferences(user.id, db_session)
    plugin = fetch_editable_skill(
        plugin_id,
        user=user,
        db_session=db_session,
        lock_for_update=True,
        any_plugin=True,
    )
    if plugin is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Plugin not found.")
    refuse_if_synced(plugin)
    with check_skill_limit(db_session, user.id):
        version = add_plugin_version__no_commit(
            plugin=plugin,
            content=content,
            base_version_id=base_version_id,
            created_by=user,
            skip_if_unchanged=skip_if_unchanged,
            db_session=db_session,
        )
    return plugin, version


def add_uploaded_plugin_version__no_commit(
    plugin_id: UUID,
    content: PluginVersionContent,
    user: User,
    db_session: Session,
) -> tuple[Plugin, PluginVersion, bool]:
    """The plugin, its current version, and False when the files equal the
    current version's files and no version was added."""
    plugin, version = _add_plugin_version_for_user__no_commit(
        plugin_id, content, None, True, user, db_session
    )
    if version is not None:
        return plugin, version, True
    if plugin.current_version_id is None:
        raise RuntimeError("Bug: a plugin with a version has a current version.")
    return (
        plugin,
        get_plugin_version(plugin.id, plugin.current_version_id, db_session),
        False,
    )


def skill_enabled_for_user(plugin_id: UUID, user: User, db_session: Session) -> bool:
    """The user turned the skill on and it loses no name."""
    return _user_skill_selection(user, db_session).enabled(plugin_id)


def skill_name_conflicts(
    skill_names: Collection[str],
    plugin_id: UUID | None,
    user: User,
    db_session: Session,
) -> list[str]:
    """The names of the other skills and plugins the user runs that hold one
    of ``skill_names``. Each one keeps a new plugin with these names off
    (``enable_new_skill_if_name_available__no_commit``)."""
    selection = _user_skill_selection(user, db_session)
    return sorted(
        {
            state.plugin_name
            for state in selection.other_skills_named(skill_names, plugin_id)
        }
    )


def restore_plugin_version__no_commit(
    plugin_id: UUID,
    content: PluginVersionContent,
    base_version_id: UUID,
    user: User,
    db_session: Session,
) -> PluginVersion | None:
    """None, and no write, when the content equals the current version."""
    return _add_plugin_version_for_user__no_commit(
        plugin_id, content, base_version_id, True, user, db_session
    )[1]


def lock_skill_for_save(plugin: Plugin, user: User, db_session: Session) -> None:
    """Take the save locks in the toggle's order, the user's lock and then the
    plugin row, and check that the user may still edit the skill: the edit
    check before the locks can be stale by now. 404 otherwise."""
    refuse_if_synced(plugin)
    lock_user_skill_preferences(user.id, db_session)
    if (
        fetch_editable_skill(
            plugin.id, user=user, db_session=db_session, lock_for_update=True
        )
        is None
    ):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")


def replace_skill_bundle(
    *,
    skill: Plugin,
    ingested: IngestedBundle,
    base_version_id: UUID | None,
    user: User,
    skip_if_unchanged: bool,
    db_session: Session,
    previous_manifest: Callable[[], list[PluginFileEntry]] | None = None,
) -> PluginVersion | None:
    """Add a plugin version with the new bundle. Takes the save locks
    (``lock_skill_for_save``) itself, so the caller can ingest the bundle
    without holding them.

    Returns None, and changes nothing, when ``skip_if_unchanged`` is set and
    the files did not change; the caller then deletes the new blob. The
    previous bundle stays: older versions still point at it. A version that
    puts the acting user past the skill limit is refused with 413.
    """
    lock_skill_for_save(skill, user, db_session)
    with check_skill_limit(db_session, user.id):
        return add_plugin_version__no_commit(
            plugin=skill,
            content=ingested.content,
            base_version_id=base_version_id,
            created_by=user,
            skip_if_unchanged=skip_if_unchanged,
            previous_manifest=previous_manifest,
            db_session=db_session,
        )


def _publish_requested(
    plugin: Plugin,
    public_permission: SkillSharePermission | None,
    db_session: Session,
) -> bool:
    """Check a request for organization access to a custom skill, and return
    whether it publishes. VIEWER publishes. None keeps the skill private and is
    refused for a published skill, because publishing is one-way.
    Organization-wide EDITOR is refused; editors are named users and groups."""
    if public_permission == SkillSharePermission.EDITOR:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "The organization cannot get edit access to a skill. Share it with "
            "users or groups as editors instead.",
        )
    if public_permission is None:
        if is_published(plugin, db_session):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "This skill is published to the organization. Publishing cannot "
                "be undone, so the skill cannot be made private.",
            )
        return False
    return True


def set_skill_public_permission(
    *,
    skill: Plugin,
    public_permission: SkillSharePermission | None,
    db_session: Session,
) -> None:
    """Publish a custom skill (VIEWER) or keep it private (None), with no
    permission check. Routes use ``share_skill__no_commit``."""
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

    if selection is None:
        selection = _user_skill_selection(user, db_session)
    states: dict[UUID, SkillUserState] = {}
    for skill_id, built_in_skill_id in db_session.execute(
        select(Skill.id, Skill.built_in_skill_id).where(
            Skill.id.in_(requested_ids), Skill.built_in_skill_id.is_not(None)
        )
    ):
        states[skill_id] = SkillUserState(
            enabled=built_in_skill_id not in EXTERNAL_APP_SKILL_ID_TO_APP_TYPE
            or built_in_skill_id in selection.built_in_app_skills,
            can_toggle=False,
        )
    built_in_names = {skill.name for skill in selection.built_ins}
    for skill_id in requested_ids - states.keys():
        state = selection.states.get(skill_id)
        name_held_by: tuple[str, ...] = ()
        if state is not None and state.can_run and skill_id in selection.hidden:
            name_held_by = tuple(
                sorted(
                    {
                        other.plugin_name
                        for other in selection.other_skills_named(
                            state.skill_names, skill_id
                        )
                        if other.plugin_id not in selection.hidden
                    }
                    | (built_in_names & set(state.skill_names))
                )
            )
        states[skill_id] = SkillUserState(
            enabled=selection.enabled(skill_id),
            name_held_by=name_held_by,
            can_toggle=state is not None
            and state.version_is_valid is not False
            and state.installation_policy != PluginInstallationPolicy.REQUIRED,
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
) -> StoredSkill:
    lock_user_skill_preferences(user.id, db_session)
    skill = fetch_skill(skill_id, user=user, db_session=db_session)
    if skill is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            "Skill is not visible.",
        )

    def checked_conflicts() -> list[UUID]:
        """Refuse the switch, or return the skills it turns off."""
        selection = _user_skill_selection(user, db_session)
        state = skill_user_states(user, [skill.id], db_session, selection)[skill.id]
        if not state.can_toggle:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "This skill cannot be enabled or disabled.",
            )
        if not enabled:
            return []
        target = selection.states.get(skill.id)
        names = target.skill_names if target is not None else (skill.name,)
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
                extra={
                    "conflict_names": sorted({other.plugin_name for other in others})
                },
            )
        return conflicts

    conflicts = checked_conflicts()
    # One id order for the target and its conflicts, so two users who switch
    # between the same skills cannot deadlock on the plugin rows.
    locked_plugin_ids = list(
        db_session.scalars(
            select(Plugin.id)
            .where(Plugin.id.in_([skill.id, *conflicts]))
            .order_by(Plugin.id)
            .with_for_update(of=Plugin)
        )
    )
    # An admin change committed while this waited for the locks can refuse
    # the switch, such as a new REQUIRED setting.
    if checked_conflicts() != conflicts:
        raise OnyxError(
            OnyxErrorCode.CONFLICT, "This skill changed. Reload and try again."
        )
    if enabled:
        limit: AbstractContextManager[None] = check_skill_limit(db_session, user.id)
    else:
        # A turn-off can let a same-name skill run, but is never refused.
        lock_user_skill_preferences(user.id, db_session)
        limit = nullcontext()
    with limit:
        set_plugin_preferences__no_commit(
            user.id,
            [plugin_id for plugin_id in locked_plugin_ids if plugin_id != skill.id],
            False,
            db_session,
        )
        set_plugin_preferences__no_commit(user.id, [skill.id], enabled, db_session)
    return skill


def set_skill_installation_policy(
    skill: Plugin,
    policy: PluginInstallationPolicy | None,
    db_session: Session,
) -> None:
    """Set the company install setting of a custom skill, with no permission
    check. None follows the marketplace default. Routes use
    ``share_skill__no_commit``."""
    apply_plugin_access_change__no_commit(
        [skill.id],
        PluginAccessChange(company_installation_policy=policy),
        None,
        db_session,
    ).raise_first_failure()


def replace_skill_shares(
    *,
    skill: Plugin,
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


def fetch_new_skill_owner(new_owner_user_id: UUID, db_session: Session) -> User:
    """The user that can receive skill ownership, or an OnyxError."""
    target = fetch_user_by_id(db_session, new_owner_user_id)
    if target is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "New owner not found.")
    if not target.is_active:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Ownership can only be transferred to an active user.",
        )
    if target.account_type is not None and target.account_type != AccountType.STANDARD:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Ownership cannot be transferred to bots or service accounts.",
        )
    return target


def transfer_skill_ownership(
    *,
    skill: Plugin,
    new_owner_user_id: UUID,
    db_session: Session,
    on_name_clash: NameClashAction = "raise",
) -> None:
    """Make another user the owner. The previous owner keeps EDITOR. A private
    skill moves to the new owner's "My uploads". On a name clash there,
    "raise" refuses with CONFLICT and "rename" takes the next free name. A
    published skill stays published."""
    refuse_if_synced(skill)
    previous_owner_user_id = skill.author_user_id
    if new_owner_user_id == previous_owner_user_id:
        return

    try:
        transfer_plugin__no_commit(
            skill.id, new_owner_user_id, db_session, on_name_clash
        )
    except IntegrityError as e:
        if is_fk_violation(e):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "New owner user does not exist.",
            ) from e
        raise
    # The author has no share, so the new owner's share goes.
    apply_plugin_access_change__no_commit(
        [skill.id],
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


def transfer_private_plugins__no_commit(
    *,
    user_id: UUID,
    new_owner_user_id: UUID,
    db_session: Session,
) -> PrivatePluginsTransfer:
    """Transfer each private plugin that blocks the user's delete to the new
    owner. A name clash takes the next free name."""
    if new_owner_user_id == user_id:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "The new owner must be a different user.",
        )
    fetch_new_skill_owner(new_owner_user_id, db_session)
    # Lock in id order, as the other plugin writers do, then rename in name
    # order.
    locked = db_session.scalars(
        private_plugins_blocking_user_delete(user_id)
        .order_by(None)
        .order_by(Plugin.id)
        .with_for_update(of=Plugin)
    ).all()
    plugins = sorted(locked, key=lambda plugin: (plugin.name, plugin.id))
    plugin_ids = [plugin.id for plugin in plugins]
    affected_user_ids = affected_user_ids_for_plugins(plugin_ids, db_session)
    renames: list[PluginRename] = []
    for plugin in plugins:
        old_name = plugin.name
        transfer_skill_ownership(
            skill=plugin,
            new_owner_user_id=new_owner_user_id,
            db_session=db_session,
            on_name_clash="rename",
        )
        if plugin.name != old_name:
            renames.append(
                PluginRename(
                    plugin_id=plugin.id, old_name=old_name, new_name=plugin.name
                )
            )
    affected_user_ids |= affected_user_ids_for_plugins(plugin_ids, db_session)
    return PrivatePluginsTransfer(
        plugin_ids=plugin_ids, renames=renames, affected_user_ids=affected_user_ids
    )


def delete_skill(skill: Plugin, db_session: Session) -> list[str]:
    """Hard-delete a custom skill's plugin, and return every bundle file of
    its versions for caller cleanup. The caller holds the plugin row lock.

    Also deletes the old skill row with the same id, so a rollback does not
    show the skill again."""
    bundle_file_ids = {
        file_id
        for file_id in db_session.scalars(
            select(PluginVersion.bundle_file_id).where(
                PluginVersion.plugin_id == skill.id
            )
        )
        if file_id is not None
    }
    # Cascades to its versions, skills, shares and choices.
    db_session.execute(delete(Plugin).where(Plugin.id == skill.id))
    db_session.execute(
        delete(Skill).where(Skill.id == skill.id, Skill.built_in_skill_id.is_(None))
    )
    db_session.flush()
    return sorted(bundle_file_ids)


def persist_skill_validity(
    updates: Iterable[SkillValidityUpdate],
) -> None:
    """Classify the plugin's unclassified versions that hold the observed
    bundle."""
    classified = [item for item in updates if item.bundle_file_id is not None]
    if not classified:
        return

    with get_session_with_current_tenant() as db_session:
        for validity_update in classified:
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


class SkillSharingChange(BaseModel):
    """A partial update to a skill's access, as the skills API sends it. None
    shares leave that kind unchanged; set_public_permission marks
    public_permission as supplied. ``installation_policy``: UNSET keeps it,
    None means "use the marketplace default", and a value sets that value."""

    model_config = ConfigDict(strict=True, frozen=True, arbitrary_types_allowed=True)

    public_permission: SkillSharePermission | None = None
    set_public_permission: bool = False
    installation_policy: PluginInstallationPolicy | None | UnsetType = UNSET
    user_shares: Mapping[UUID, SkillSharePermission] | None = None
    group_shares: Mapping[int, SkillSharePermission] | None = None
    # Group install settings with no change to the share. None removes one.
    group_settings: Mapping[int, PluginInstallationPolicy | None] | None = None


SkillBulkAction = Literal["enable", "disable", "delete"]


def ensure_can_edit_org_visibility(plugin: Plugin, user: User) -> None:
    refuse_if_synced(plugin)
    if plugin.author_user_id == user.id:
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


PERSONAL_SYNCED_PLUGIN_UNSHARED = (
    "Only the owner of a personal marketplace gets its plugins. "
    "Add the marketplace for the company to share them."
)


def _check_skill_access_change(
    plugin: Plugin, change: SkillSharingChange, user: User, db_session: Session
) -> None:
    if is_personal_synced(plugin) and (
        change.user_shares
        or change.group_shares
        or change.group_settings
        or not isinstance(change.installation_policy, UnsetType)
    ):
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, PERSONAL_SYNCED_PLUGIN_UNSHARED)
    if change.set_public_permission:
        ensure_can_edit_org_visibility(plugin, user)
        _publish_requested(plugin, change.public_permission, db_session)


def publish_skill__no_commit(
    plugin: Plugin,
    base_version_id: UUID | None,
    user: User,
    db_session: Session,
) -> set[UUID]:
    """Publish the current version of a skill: a first publish for a private
    skill, a publish update for a published one. Only the author or an
    organization-wide manager publishes. Under the Publishing setting this can
    make a review request instead, or be refused. The caller holds the plugin
    row lock. Returns the affected users."""
    ensure_can_edit_org_visibility(plugin, user)
    check_base_version(plugin, base_version_id)
    if plugin.published_version_id == plugin.current_version_id:
        return set()
    before = affected_user_ids_for_plugins([plugin.id], db_session)
    publish_or_request_review__no_commit(
        plugin, plugin.current_version_id, user, "raise", db_session
    )
    return before | affected_user_ids_for_plugins([plugin.id], db_session)


def _check_pending(plugin: Plugin, version_id: UUID, db_session: Session) -> None:
    """Refuse a version that is not the plugin's pending request."""
    get_plugin_version(plugin.id, version_id, db_session)
    if plugin.pending_version_id != version_id:
        raise OnyxError(
            OnyxErrorCode.CONFLICT, "This version has no pending publish request."
        )


def approve_skill_review__no_commit(
    plugin: Plugin, version_id: UUID, db_session: Session
) -> set[UUID]:
    """Publish the pending version of a skill. A first publish moves the skill
    to the Organization library, and a name clash there is refused with
    CONFLICT. The caller holds the plugin row lock. Returns the affected
    users."""
    _check_pending(plugin, version_id, db_session)
    before = affected_user_ids_for_plugins([plugin.id], db_session)
    publish_or_request_review__no_commit(plugin, version_id, None, "raise", db_session)
    return before | affected_user_ids_for_plugins([plugin.id], db_session)


def deny_skill_review__no_commit(
    plugin: Plugin, version_id: UUID, db_session: Session
) -> None:
    """Clear the pending request. The caller holds the plugin row lock."""
    _check_pending(plugin, version_id, db_session)
    plugin.pending_version_id = None
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
    plugin: Plugin,
    change: SkillSharingChange,
    user: User,
    db_session: Session,
    on_name_clash: NameClashAction = "raise",
) -> set[UUID]:
    """Apply an access change to one skill through its plugin and return
    every user whose sandbox is affected, before or after the change. Supplied
    user and group shares replace the current ones."""
    _check_skill_access_change(plugin, change, user, db_session)
    result = apply_plugin_access_change__no_commit(
        [plugin.id],
        _plugin_access_change(change, PluginAccessMode.REPLACE, on_name_clash),
        user,
        db_session,
    )
    result.raise_first_failure()
    return result.affected_user_ids


class SkillBulkShareResult(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, arbitrary_types_allowed=True)

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
        plugin = fetch_editable_skill(
            skill_id,
            user=user,
            db_session=db_session,
            lock_for_update=True,
            any_plugin=True,
        )
        if plugin is None:
            failed[skill_id] = "Skill not found"
            continue
        try:
            _check_skill_access_change(plugin, change, user, db_session)
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


def may_delete_skill(
    *, synced: bool, published: bool, required_for_anyone: bool, user: User
) -> bool:
    """A user who can edit a skill deletes it, except a published skill or one
    REQUIRED for anyone, which needs organization-wide MANAGE_PLUGINS. A
    plugin synced from GitHub is not deleted here; removing its marketplace
    deletes it. The delete route and ``SkillResponse.can_delete`` use this one
    rule."""
    if synced:
        return False
    return not (published or required_for_anyone) or has_global_permission(
        user, Permission.MANAGE_PLUGINS
    )


def delete_skill_for_user__no_commit(
    plugin: Plugin, user: User, db_session: Session
) -> tuple[set[UUID], list[str]]:
    """Delete a skill the user may edit. Only a user with organization-wide
    MANAGE_PLUGINS can delete a published skill. Returns the affected users and
    the bundle file ids for caller cleanup."""
    refuse_if_synced(plugin)
    published = is_published(plugin, db_session)
    required_for_anyone = bool(
        db_session.scalar(
            select(
                exists().where(
                    Plugin.id == plugin.id,
                    Marketplace.id == Plugin.marketplace_id,
                    plugin_required_for_anyone(Plugin, Marketplace),
                )
            )
        )
    )
    if not may_delete_skill(
        synced=is_synced(plugin),
        published=published,
        required_for_anyone=required_for_anyone,
        user=user,
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "This skill is published to the organization. Only an admin can delete it."
            if published
            else "Only an organization-wide skill manager can delete a required skill.",
        )
    affected = affected_user_ids_for_plugins([plugin.id], db_session)
    return affected, delete_skill(plugin, db_session)


def create_skill_from_bundle__no_commit(
    ingested: IngestedBundle,
    change: SkillSharingChange | None,
    auto_enable: bool,
    user: User,
    db_session: Session,
) -> tuple[Plugin, bool, set[UUID]]:
    """Create a skill from a stored bundle inside a savepoint, so a name
    conflict or a rejected access change rolls back this skill only. Returns
    the plugin, whether it was enabled for the user, and the affected users."""
    with db_session.begin_nested():
        plugin, affected = create_custom_skill__no_commit(
            ingested, user, db_session, change=change
        )
        enabled = auto_enable and enable_new_skill_if_name_available__no_commit(
            plugin, user.id, db_session
        )
        if enabled:
            affected.add(user.id)
    return plugin, enabled, affected


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
        plugin = fetch_editable_skill(
            skill_id,
            user=user,
            db_session=db_session,
            lock_for_update=True,
            any_plugin=True,
        )
        if plugin is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
        return delete_skill_for_user__no_commit(plugin, user, db_session)
