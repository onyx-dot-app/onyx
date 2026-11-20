from collections.abc import Iterable
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission, has_permission
from onyx.db.app_skill import built_in_app_skills
from onyx.db.enums import (
    Permission,
    PermissionAuthority,
    SkillAccessLevel,
    SkillSharePermission,
)
from onyx.db.models import Plugin, Skill, User
from onyx.db.persona_sharing import (
    get_user_group_ids_for_user,
)
from onyx.db.plugin import get_version_manifest, list_version_skills
from onyx.db.plugin_access import (
    PluginAccess,
    get_visible_plugin_ids,
    load_plugin_access,
    plugin_ids_in_managed_scope,
)
from onyx.db.scoped_permissions import fetch_managed_group_ids
from onyx.db.skill import (
    SkillUserState,
    StoredSkill,
    may_delete_skill,
    skill_user_states,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.plugin_needs import (
    PluginNeedView,
    need_counts,
    needs_of_versions,
)
from onyx.server.features.skill.models import (
    PluginDetail,
    PluginSkillSummary,
    SkillGroupSummary,
    SkillPreviewResponse,
    SkillResponse,
    SkillsList,
)
from onyx.skills.built_in import (
    BUILT_IN_SKILLS,
    EXTERNAL_APP_SKILL_ID_TO_APP_TYPE,
)
from onyx.skills.bundle import SKILL_MD_NAME, strip_skill_md_frontmatter
from onyx.skills.content import (
    read_builtin_skill_instructions,
    read_version_contents,
)
from onyx.skills.rendering import render_external_app_files
from onyx.utils.logger import setup_logger

logger = setup_logger()


def user_permission_for_skill(
    access: PluginAccess,
    user: User,
    user_group_ids: set[int],
    in_managed_scope: bool = False,
) -> SkillAccessLevel | None:
    """Read-side mirror of ``onyx.db.skill.fetch_editable_skill``; the two must
    agree or the UI offers actions the write path rejects. ``access`` holds the
    plugin grants of a custom skill; ``in_managed_scope`` is
    ``plugin_in_managed_scope`` for a group manager. There is no
    organization-wide edit."""
    if access.author_user_id == user.id:
        return SkillAccessLevel.OWNER

    if has_global_permission(user, Permission.MANAGE_PLUGINS):
        return SkillAccessLevel.EDITOR

    share_permissions = {
        share.permission for share in access.user_shares if share.user_id == user.id
    } | {
        share.permission
        for share in access.group_shares
        if share.group_id in user_group_ids
    }
    if SkillSharePermission.EDITOR in share_permissions or in_managed_scope:
        return SkillAccessLevel.EDITOR

    if access.published or share_permissions:
        return SkillAccessLevel.VIEWER

    return None


def _access_of(plugin: Plugin, plugin_access: dict[UUID, PluginAccess]) -> PluginAccess:
    access = plugin_access.get(plugin.id)
    if access is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    return access


def _managed_scope(
    user: User, skill_ids: Iterable[UUID], db_session: Session
) -> tuple[set[int], set[UUID]]:
    """The groups a group manager manages, and the skills among ``skill_ids``
    in their managed scope. Both empty for other users."""
    if (
        has_permission(user, Permission.MANAGE_PLUGINS)
        is not PermissionAuthority.SCOPED
    ):
        return set(), set()
    return fetch_managed_group_ids(user, db_session), plugin_ids_in_managed_scope(
        skill_ids, user, db_session
    )


def _group_summaries(
    access: PluginAccess,
    user_permission: SkillAccessLevel | None,
    managed_user_group_ids: set[int] | None,
) -> list[SkillGroupSummary]:
    """The group rows the caller may see: every row for a user who may edit
    the skill (the rule of the share details), else the rows of the groups a
    scoped manager manages."""
    can_edit = user_permission in (SkillAccessLevel.OWNER, SkillAccessLevel.EDITOR)
    managed = managed_user_group_ids or set()
    return [
        SkillGroupSummary(
            group_id=row.group_id,
            group_name=row.group_name,
            permission=row.permission,
            installation_policy=row.installation_policy,
        )
        for row in access.group_rows
        if can_edit or row.group_id in managed
    ]


def skill_response_for_user(
    skill: StoredSkill,
    user: User,
    db_session: Session,
    *,
    state: SkillUserState | None = None,
    user_group_ids: set[int] | None = None,
    managed_user_group_ids: set[int] | None = None,
    managed_scope_ids: set[UUID] | None = None,
    include_share_details: bool = False,
    plugin_access: dict[UUID, PluginAccess] | None = None,
    shown_version_id: UUID | None = None,
    needs: dict[UUID, list[PluginNeedView]] | None = None,
    include_plugin_detail: bool = False,
) -> SkillResponse:
    """``shown_version_id`` is the version whose files the response shows, and
    so the edit base; by default the plugin's current version. When given, the
    counts and plugin detail also describe it, else the version the user
    runs. ``needs`` are the need views by version (``needs_of_versions``);
    read when not given. ``include_plugin_detail`` adds the skills, needs and
    plugin.json fields."""
    if state is None:
        state = skill_user_states(user, [skill.id], db_session)[skill.id]
    if isinstance(skill, Skill):
        definition = BUILT_IN_SKILLS.get(skill.built_in_skill_id or "")
        if definition is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
        return SkillResponse.from_builtin(
            skill,
            definition,
            db_session,
            enabled=state.enabled,
            can_toggle=state.can_toggle,
        )

    if user_group_ids is None:
        user_group_ids = get_user_group_ids_for_user(db_session, user.id)
    if managed_user_group_ids is None or managed_scope_ids is None:
        managed_user_group_ids, managed_scope_ids = _managed_scope(
            user, [skill.id], db_session
        )
    if plugin_access is None:
        plugin_access = load_plugin_access([skill.id], user.id, db_session)
    access = _access_of(skill, plugin_access)
    described = shown_version_id or access.version_user_runs
    if shown_version_id is None:
        shown_version_id = access.current_version_id
    user_permission = user_permission_for_skill(
        access, user, user_group_ids, skill.id in managed_scope_ids
    )
    if needs is None:
        needs = needs_of_versions(user, [described], db_session)
    version_needs = needs.get(described, [])
    return SkillResponse.from_custom(
        skill,
        access,
        enabled=state.enabled,
        can_toggle=state.can_toggle,
        required_for_user=state.required,
        name_held_by=list(state.name_held_by),
        user_permission=user_permission,
        can_delete=user_permission in (SkillAccessLevel.OWNER, SkillAccessLevel.EDITOR)
        and may_delete_skill(
            synced=access.synced,
            published=access.published,
            required_for_anyone=access.required_for_anyone,
            user=user,
        ),
        include_share_details=include_share_details,
        # Edit access from managed scope alone shows only the managed groups.
        group_summaries=_group_summaries(
            access,
            user_permission_for_skill(access, user, user_group_ids),
            managed_user_group_ids,
        ),
        current_version_id=shown_version_id,
        counts=need_counts(version_needs),
        plugin_detail=(
            plugin_version_detail(described, version_needs, db_session)
            if include_plugin_detail
            else None
        ),
    )


def plugin_version_detail(
    version_id: UUID, needs: list[PluginNeedView], db_session: Session
) -> PluginDetail:
    return PluginDetail(
        manifest=get_version_manifest(version_id, db_session),
        skills=[
            PluginSkillSummary(
                path=skill_row.path,
                name=skill_row.name,
                description=skill_row.description,
            )
            for skill_row in list_version_skills(version_id, db_session)
        ],
        needs=needs,
    )


def skills_list_response_for_user(
    rows: list[StoredSkill],
    user: User,
    db_session: Session,
) -> SkillsList:
    builtins: list[SkillResponse] = []
    customs: list[SkillResponse] = []
    custom_ids = [skill.id for skill in rows if isinstance(skill, Plugin)]
    user_group_ids = get_user_group_ids_for_user(db_session, user.id)
    managed_user_group_ids, managed_scope_ids = _managed_scope(
        user, custom_ids, db_session
    )
    states = skill_user_states(user, (skill.id for skill in rows), db_session)
    plugin_access = load_plugin_access(custom_ids, user.id, db_session)
    needs = needs_of_versions(
        user,
        (access.version_user_runs for access in plugin_access.values()),
        db_session,
    )
    member_visible_ids = (
        get_visible_plugin_ids(user.id, db_session)
        if has_global_permission(user, Permission.MANAGE_PLUGINS)
        else None
    )
    for skill in rows:
        if isinstance(skill, Skill):
            if skill.built_in_skill_id not in BUILT_IN_SKILLS:
                logger.warning(
                    "Skill row %s references unknown built-in %s; hiding from listing",
                    skill.name,
                    skill.built_in_skill_id,
                )
                continue
            # An app built-in the user does not get.
            if not states[skill.id].enabled:
                continue

        response = skill_response_for_user(
            skill,
            user,
            db_session,
            state=states[skill.id],
            user_group_ids=user_group_ids,
            managed_user_group_ids=managed_user_group_ids,
            managed_scope_ids=managed_scope_ids,
            plugin_access=plugin_access,
            needs=needs,
        )
        if member_visible_ids is not None and isinstance(skill, Plugin):
            response.member_visible = skill.id in member_visible_ids
        (customs if isinstance(skill, Plugin) else builtins).append(response)

    return SkillsList(builtins=builtins, customs=customs)


def skill_preview_response(
    skill: StoredSkill,
    user: User,
    db_session: Session,
) -> SkillPreviewResponse:
    if isinstance(skill, Skill):
        definition = BUILT_IN_SKILLS.get(skill.built_in_skill_id or "")
        if definition is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
        app_type = EXTERNAL_APP_SKILL_ID_TO_APP_TYPE.get(definition.built_in_skill_id)
        if app_type is not None and definition.has_template:
            external_app_id = built_in_app_skills(user.id, db_session).get(
                definition.built_in_skill_id
            )
            rendered = render_external_app_files(
                db_session, external_app_id, app_type, definition.source_dir
            )
            instructions = strip_skill_md_frontmatter(rendered[SKILL_MD_NAME])
        else:
            instructions = read_builtin_skill_instructions(definition)
        return SkillPreviewResponse.from_builtin(
            skill,
            instructions_markdown=instructions,
        )

    access = _access_of(skill, load_plugin_access([skill.id], user.id, db_session))
    if not access.is_skill:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "This is a plugin, not one skill. Open the plugin to read its skills.",
        )
    contents = read_version_contents(access.version_user_runs, db_session)
    return SkillPreviewResponse.from_custom(
        skill,
        access,
        instructions_markdown=contents.instructions_markdown,
        files=contents.files,
    )
