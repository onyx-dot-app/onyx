from collections.abc import Iterable
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission, has_permission
from onyx.db.enums import (
    Permission,
    PermissionAuthority,
    SkillAccessLevel,
    SkillSharePermission,
)
from onyx.db.external_app import (
    SkillExternalAppDependencyState,
    get_skill_external_app_dependencies,
)
from onyx.db.models import Skill, User
from onyx.db.persona_sharing import (
    get_user_group_ids_for_user,
)
from onyx.db.plugin_access import (
    PluginAccess,
    load_plugin_access,
    plugin_ids_in_managed_scope,
)
from onyx.db.skill import SkillUserState, may_delete_skill, skill_user_states
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill.models import (
    SkillExternalAppDependencyResponse,
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


def _dependency_response(
    dependency: SkillExternalAppDependencyState | None,
) -> SkillExternalAppDependencyResponse | None:
    if dependency is None:
        return None
    return SkillExternalAppDependencyResponse(
        external_app_id=dependency.external_app_id,
        name=dependency.name,
        enabled=dependency.enabled,
        ready=dependency.ready,
    )


def user_permission_for_skill(
    skill: Skill,
    access: PluginAccess | None,
    user: User,
    user_group_ids: set[int],
    in_managed_scope: bool = False,
) -> SkillAccessLevel | None:
    """Read-side mirror of ``_is_editable_by_user``; the two must agree or the UI
    offers actions the write path rejects. ``access`` holds the plugin grants of
    a custom skill; ``in_managed_scope`` is ``plugin_in_managed_scope`` for a
    group manager. There is no organization-wide edit."""
    if not skill.is_custom:
        return SkillAccessLevel.VIEWER
    if access is None:
        return (
            SkillAccessLevel.EDITOR
            if has_global_permission(user, Permission.MANAGE_PLUGINS)
            else None
        )

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


def _managed_scope(
    user: User, skill_ids: Iterable[UUID], db_session: Session
) -> set[UUID]:
    """The skills among ``skill_ids`` in a group manager's managed scope.
    Empty for other users."""
    if (
        has_permission(user, Permission.MANAGE_PLUGINS)
        is not PermissionAuthority.SCOPED
    ):
        return set()
    return plugin_ids_in_managed_scope(skill_ids, user, db_session)


def skill_response_for_user(
    skill: Skill,
    user: User,
    db_session: Session,
    *,
    state: SkillUserState | None = None,
    user_group_ids: set[int] | None = None,
    managed_scope_ids: set[UUID] | None = None,
    include_share_details: bool = False,
    plugin_access: dict[UUID, PluginAccess] | None = None,
    shown_version_id: UUID | None = None,
) -> SkillResponse:
    """``shown_version_id`` is the version whose files the response shows, and
    so the edit base; by default the plugin's current version."""
    if state is None:
        state = skill_user_states(user, [skill.id], db_session)[skill.id]
    if skill.built_in_skill_id is not None:
        definition = BUILT_IN_SKILLS.get(skill.built_in_skill_id)
        if definition is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
        return SkillResponse.from_builtin(
            skill,
            definition,
            db_session,
            enabled=state.enabled,
            can_toggle=state.can_toggle,
            external_app=_dependency_response(state.external_app_dependency),
        )

    if user_group_ids is None:
        user_group_ids = get_user_group_ids_for_user(db_session, user.id)
    if managed_scope_ids is None:
        managed_scope_ids = _managed_scope(user, [skill.id], db_session)
    if plugin_access is None:
        plugin_access = load_plugin_access([skill.id], user.id, db_session)
    access = plugin_access.get(skill.id)
    if shown_version_id is None and access is not None:
        shown_version_id = access.current_version_id
    user_permission = user_permission_for_skill(
        skill, access, user, user_group_ids, skill.id in managed_scope_ids
    )
    return SkillResponse.from_custom(
        skill,
        access,
        enabled=state.enabled,
        can_toggle=state.can_toggle,
        required_for_user=state.required,
        user_permission=user_permission,
        can_delete=user_permission in (SkillAccessLevel.OWNER, SkillAccessLevel.EDITOR)
        and may_delete_skill(
            published=access is not None and access.published,
            required_for_anyone=access is not None and access.required_for_anyone,
            user=user,
        ),
        include_share_details=include_share_details,
        external_app=_dependency_response(state.external_app_dependency),
        current_version_id=shown_version_id,
    )


def skills_list_response_for_user(
    rows: list[Skill],
    user: User,
    db_session: Session,
) -> SkillsList:
    builtins: list[SkillResponse] = []
    customs: list[SkillResponse] = []
    user_group_ids = get_user_group_ids_for_user(db_session, user.id)
    managed_scope_ids = _managed_scope(
        user, (skill.id for skill in rows if skill.is_custom), db_session
    )
    states = skill_user_states(user, (skill.id for skill in rows), db_session)
    plugin_access = load_plugin_access(
        (skill.id for skill in rows if skill.is_custom), user.id, db_session
    )
    for skill in rows:
        if (
            skill.built_in_skill_id is not None
            and skill.built_in_skill_id not in BUILT_IN_SKILLS
        ):
            logger.warning(
                "Skill row %s references unknown built-in %s; hiding from listing",
                skill.name,
                skill.built_in_skill_id,
            )
            continue

        response = skill_response_for_user(
            skill,
            user,
            db_session,
            state=states[skill.id],
            user_group_ids=user_group_ids,
            managed_scope_ids=managed_scope_ids,
            plugin_access=plugin_access,
        )
        (customs if skill.is_custom else builtins).append(response)

    return SkillsList(builtins=builtins, customs=customs)


def skill_preview_response(
    skill: Skill,
    user: User,
    db_session: Session,
) -> SkillPreviewResponse:
    # Both sources can be gated on an external app — a built-in provider's
    # associated skill is a built-in row.
    external_app = _dependency_response(
        get_skill_external_app_dependencies(
            db_session,
            user,
            [skill.id],
        ).get(skill.id)
    )
    if skill.built_in_skill_id is not None:
        definition = BUILT_IN_SKILLS.get(skill.built_in_skill_id)
        if definition is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
        app_type = EXTERNAL_APP_SKILL_ID_TO_APP_TYPE.get(definition.built_in_skill_id)
        if app_type is not None and definition.has_template:
            rendered = render_external_app_files(
                db_session, skill, app_type, definition.source_dir
            )
            instructions = strip_skill_md_frontmatter(rendered[SKILL_MD_NAME])
        else:
            instructions = read_builtin_skill_instructions(definition)
        return SkillPreviewResponse.from_builtin(
            skill,
            instructions_markdown=instructions,
            external_app=external_app,
        )

    access = load_plugin_access([skill.id], user.id, db_session).get(skill.id)
    if access is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill has no plugin version.")
    return SkillPreviewResponse.from_custom(
        skill,
        access,
        instructions_markdown=read_version_contents(
            access.version_user_runs, db_session
        ).instructions_markdown,
        external_app=external_app,
    )
