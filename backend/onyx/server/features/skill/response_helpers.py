from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.models import Skill
from onyx.db.skill import get_group_ids_for_skill
from onyx.db.skill import skill_ids_with_grants
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill.models import BuiltinSkillResponse
from onyx.server.features.skill.models import CustomSkillResponse
from onyx.server.features.skill.models import SkillPreviewResponse
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.content import read_builtin_skill_instructions
from onyx.skills.content import read_custom_skill_bundle_instructions
from onyx.utils.logger import setup_logger

logger = setup_logger()


def split_skill_rows(
    rows: list[Skill],
    db_session: Session,
    *,
    include_grants: bool,
) -> tuple[list[BuiltinSkillResponse], list[CustomSkillResponse]]:
    """Partition a flat row list into built-in + custom responses.

    A row with an unknown ``built_in_skill_id`` (definition was removed
    in code without cleaning up the seeded row) is logged and dropped -
    we don't surface a half-broken built-in to admins. ``include_grants``
    only applies to custom skills; built-ins are not group-shareable.
    """
    builtins: list[BuiltinSkillResponse] = []
    customs: list[CustomSkillResponse] = []

    # User paths withhold group ids but still need grant existence so a
    # grants-shared skill isn't reported as personal.
    custom_ids = [s.id for s in rows if s.built_in_skill_id is None]
    granted_skill_ids: set[UUID] = set()
    if custom_ids:
        granted_skill_ids = skill_ids_with_grants(custom_ids, db_session)

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
            builtins.append(
                BuiltinSkillResponse.from_row(skill, definition, db_session)
            )
        elif include_grants:
            group_ids = get_group_ids_for_skill(skill.id, db_session)
            customs.append(
                CustomSkillResponse.from_model(
                    skill,
                    group_ids=group_ids,
                    has_grants=skill.id in granted_skill_ids,
                )
            )
        else:
            customs.append(
                CustomSkillResponse.from_model(
                    skill,
                    group_ids=[],
                    has_grants=skill.id in granted_skill_ids,
                )
            )

    return builtins, customs


def preview_response_for_skill(
    skill: Skill,
) -> SkillPreviewResponse:
    if skill.built_in_skill_id is not None:
        definition = BUILT_IN_SKILLS.get(skill.built_in_skill_id)
        if definition is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
        return SkillPreviewResponse.from_builtin(
            skill,
            instructions_markdown=read_builtin_skill_instructions(definition),
        )

    instructions_markdown = read_custom_skill_bundle_instructions(skill)
    return SkillPreviewResponse.from_custom(
        skill,
        instructions_markdown=instructions_markdown,
    )
