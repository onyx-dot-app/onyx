from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.enums import SkillAccessLevel
from onyx.db.enums import SkillSharePermission
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.db.persona_sharing import get_curated_user_group_ids_for_user
from onyx.db.persona_sharing import get_user_group_ids_for_user
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill.models import SkillPreviewResponse
from onyx.server.features.skill.models import SkillResponse
from onyx.server.features.skill.models import SkillsList
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.content import read_builtin_skill_instructions
from onyx.skills.content import read_custom_skill_bundle_instructions
from onyx.utils.logger import setup_logger

logger = setup_logger()


def user_permission_for_skill(
    skill: Skill,
    user: User,
    user_group_ids: set[int],
    curated_user_group_ids: set[int] | None = None,
) -> SkillAccessLevel | None:
    if skill.built_in_skill_id is not None:
        return SkillAccessLevel.VIEWER

    if skill.author_user_id == user.id:
        return SkillAccessLevel.OWNER

    if user.role == UserRole.ADMIN:
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
    curator_managed_group_ids = set[int]()
    if user.role == UserRole.GLOBAL_CURATOR:
        curator_managed_group_ids = user_group_ids
    elif user.role == UserRole.CURATOR:
        curator_managed_group_ids = curated_user_group_ids or set()
    is_curator_managed = (
        bool(group_share_ids)
        and bool(curator_managed_group_ids)
        and group_share_ids <= curator_managed_group_ids
    )
    has_explicit_edit = SkillSharePermission.EDITOR in share_permissions or (
        is_org_shared and skill.public_permission == SkillSharePermission.EDITOR
    )

    if has_explicit_edit or is_curator_managed:
        return SkillAccessLevel.EDITOR

    if is_org_shared or is_shared_with_user:
        return SkillAccessLevel.VIEWER

    return None


def skill_response_for_user(
    skill: Skill,
    user: User,
    db_session: Session,
    *,
    user_group_ids: set[int] | None = None,
    curated_user_group_ids: set[int] | None = None,
    include_share_details: bool = False,
) -> SkillResponse:
    if skill.built_in_skill_id is not None:
        definition = BUILT_IN_SKILLS.get(skill.built_in_skill_id)
        if definition is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
        return SkillResponse.from_builtin(skill, definition, db_session)

    if user_group_ids is None:
        user_group_ids = get_user_group_ids_for_user(db_session, user.id)
    if curated_user_group_ids is None and user.role == UserRole.CURATOR:
        curated_user_group_ids = get_curated_user_group_ids_for_user(
            db_session, user.id
        )
    return SkillResponse.from_custom(
        skill,
        user_permission=user_permission_for_skill(
            skill,
            user,
            user_group_ids,
            curated_user_group_ids,
        ),
        include_share_details=include_share_details,
    )


def skills_list_response_for_user(
    rows: list[Skill],
    user: User,
    db_session: Session,
) -> SkillsList:
    builtins: list[SkillResponse] = []
    customs: list[SkillResponse] = []
    user_group_ids = get_user_group_ids_for_user(db_session, user.id)
    curated_user_group_ids = (
        get_curated_user_group_ids_for_user(db_session, user.id)
        if user.role == UserRole.CURATOR
        else set()
    )

    for skill in rows:
        if skill.built_in_skill_id is not None:
            definition = BUILT_IN_SKILLS.get(skill.built_in_skill_id)
            if definition is None:
                logger.warning(
                    "Skill row %s references unknown built-in %s; hiding from listing",
                    skill.slug,
                    skill.built_in_skill_id,
                )
                continue
            builtins.append(SkillResponse.from_builtin(skill, definition, db_session))
            continue

        customs.append(
            skill_response_for_user(
                skill,
                user,
                db_session,
                user_group_ids=user_group_ids,
                curated_user_group_ids=curated_user_group_ids,
            )
        )

    return SkillsList(builtins=builtins, customs=customs)


def skill_preview_response(skill: Skill) -> SkillPreviewResponse:
    if skill.built_in_skill_id is not None:
        definition = BUILT_IN_SKILLS.get(skill.built_in_skill_id)
        if definition is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
        return SkillPreviewResponse.from_builtin(
            skill,
            instructions_markdown=read_builtin_skill_instructions(definition),
        )

    return SkillPreviewResponse.from_custom(
        skill,
        instructions_markdown=read_custom_skill_bundle_instructions(skill),
    )
