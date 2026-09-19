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
from onyx.db.scoped_permissions import fetch_managed_group_ids
from onyx.db.skill import SkillUserState, skill_user_states
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill.models import (
    SkillExternalAppDependencyResponse,
    SkillPreviewResponse,
    SkillResponse,
    SkillsList,
)
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.content import (
    read_builtin_skill_instructions,
    read_custom_skill_bundle_instructions,
)
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
    user: User,
    user_group_ids: set[int],
    managed_user_group_ids: set[int] | None = None,
) -> SkillAccessLevel | None:
    """Read-side mirror of ``_is_editable_by_user``; the two must agree or the UI
    offers actions the write path rejects."""
    if not skill.is_custom:
        return SkillAccessLevel.VIEWER

    if skill.author_user_id == user.id:
        return SkillAccessLevel.OWNER

    if has_global_permission(user, Permission.MANAGE_SKILLS):
        return SkillAccessLevel.EDITOR

    direct_permissions = {
        share.permission for share in skill.user_shares if share.user_id == user.id
    }
    group_permissions = {
        share.permission
        for share in skill.group_shares
        if share.user_group_id in user_group_ids
    }
    share_permissions = direct_permissions | group_permissions

    is_org_shared = skill.public_permission is not None
    is_shared_with_user = bool(share_permissions)
    group_share_ids = {share.user_group_id for share in skill.group_shares}
    # Same rule as within_managed_scope_clause: non-public, in >=1 managed group,
    # and no group outside the manager's scope.
    is_manager_managed = (
        not is_org_shared
        and bool(group_share_ids)
        and bool(managed_user_group_ids)
        and group_share_ids <= (managed_user_group_ids or set())
    )
    has_explicit_edit = SkillSharePermission.EDITOR in share_permissions or (
        is_org_shared and skill.public_permission == SkillSharePermission.EDITOR
    )

    if has_explicit_edit or is_manager_managed:
        return SkillAccessLevel.EDITOR

    if is_org_shared or is_shared_with_user:
        return SkillAccessLevel.VIEWER

    return None


def skill_response_for_user(
    skill: Skill,
    user: User,
    db_session: Session,
    *,
    state: SkillUserState | None = None,
    user_group_ids: set[int] | None = None,
    managed_user_group_ids: set[int] | None = None,
    include_share_details: bool = False,
) -> SkillResponse:
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
    if (
        managed_user_group_ids is None
        and has_permission(user, Permission.MANAGE_SKILLS) is PermissionAuthority.SCOPED
    ):
        managed_user_group_ids = fetch_managed_group_ids(user, db_session)
    return SkillResponse.from_custom(
        skill,
        enabled=state.enabled,
        can_toggle=state.can_toggle,
        user_permission=user_permission_for_skill(
            skill,
            user,
            user_group_ids,
            managed_user_group_ids,
        ),
        include_share_details=include_share_details,
        external_app=_dependency_response(state.external_app_dependency),
    )


def skills_list_response_for_user(
    rows: list[Skill],
    user: User,
    db_session: Session,
) -> SkillsList:
    builtins: list[SkillResponse] = []
    customs: list[SkillResponse] = []
    user_group_ids = get_user_group_ids_for_user(db_session, user.id)
    managed_user_group_ids = (
        fetch_managed_group_ids(user, db_session)
        if has_permission(user, Permission.MANAGE_SKILLS) is PermissionAuthority.SCOPED
        else set()
    )
    states = skill_user_states(user, (skill.id for skill in rows), db_session)
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
            managed_user_group_ids=managed_user_group_ids,
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
        return SkillPreviewResponse.from_builtin(
            skill,
            instructions_markdown=read_builtin_skill_instructions(definition),
            external_app=external_app,
        )

    return SkillPreviewResponse.from_custom(
        skill,
        instructions_markdown=read_custom_skill_bundle_instructions(skill),
        external_app=external_app,
    )
