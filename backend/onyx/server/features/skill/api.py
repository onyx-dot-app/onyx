import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import UploadFile
from pydantic import Field
from sqlalchemy.orm import Session

from onyx.auth.permissions import Permission
from onyx.auth.permissions import require_permission
from onyx.auth.users import current_curator_or_admin_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.db.skill import fetch_skill_by_id
from onyx.db.skill import fetch_skill_for_user
from onyx.db.skill import fetch_skill_for_user_by_slug
from onyx.db.skill import get_group_ids_for_skill
from onyx.db.skill import list_skills
from onyx.db.skill import list_skills_for_user
from onyx.db.skill import skill_ids_with_grants
from onyx.db.skill import SkillAccessPolicy
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill import service as skill_service
from onyx.server.features.skill.models import BuiltinSkillResponse
from onyx.server.features.skill.models import CustomSkillResponse
from onyx.server.features.skill.models import GrantsReplace
from onyx.server.features.skill.models import PersonalSkillPatchRequest
from onyx.server.features.skill.models import SkillPatchRequest
from onyx.server.features.skill.models import SkillPreviewResponse
from onyx.server.features.skill.models import SkillsList
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.bundle import read_bundle_file
from onyx.skills.content import read_builtin_skill_instructions
from onyx.skills.content import read_custom_skill_bundle_instructions
from onyx.utils.logger import setup_logger

logger = setup_logger()

admin_router = APIRouter(prefix="/admin/skills")
user_router = APIRouter(prefix="/skills")

MAX_PERSONAL_SKILLS_PER_USER = skill_service.MAX_PERSONAL_SKILLS_PER_USER
_ensure_custom = skill_service.ensure_custom_skill


def _split_rows(
    rows: list[Skill],
    db_session: Session,
    *,
    include_grants: bool,
) -> tuple[list[BuiltinSkillResponse], list[CustomSkillResponse]]:
    """Partition a flat row list into built-in + custom responses.

    A row with an unknown ``built_in_skill_id`` (definition was removed
    in code without cleaning up the seeded row) is logged and dropped —
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


def _preview_response_for_skill(
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


@admin_router.get("")
def list_skills_admin(
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> SkillsList:
    rows = list(
        list_skills(
            policy=SkillAccessPolicy.VIEW,
            user=user,
            db_session=db_session,
        )
    )
    builtins, customs = _split_rows(rows, db_session, include_grants=True)
    return SkillsList(builtins=builtins, customs=customs)


@admin_router.get("/{skill_id}/preview")
def preview_skill_admin(
    skill_id: UUID,
    _: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> SkillPreviewResponse:
    skill = fetch_skill_by_id(skill_id, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    return _preview_response_for_skill(skill)


@admin_router.post("/custom")
def create_custom_skill(
    is_public: bool = Form(False),
    group_ids: str = Form("[]"),
    bundle: UploadFile = File(...),
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> CustomSkillResponse:
    parsed_group_ids = _parse_group_ids(group_ids)
    skill = skill_service.create_admin_custom_skill(
        bundle_bytes=read_bundle_file(bundle.file),
        filename=bundle.filename,
        is_public=is_public,
        group_ids=parsed_group_ids,
        user=user,
        db_session=db_session,
    )
    return CustomSkillResponse.from_model(skill, group_ids=parsed_group_ids)


@admin_router.patch("/custom/{skill_id}")
def patch_custom_skill(
    skill_id: UUID,
    patch_req: SkillPatchRequest,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> CustomSkillResponse:
    """Toggle ``enabled``/``is_public`` on a custom skill."""
    updated = skill_service.patch_admin_custom_skill(
        skill_id=skill_id,
        patch=patch_req.to_domain(),
        user=user,
        db_session=db_session,
    )
    return CustomSkillResponse.from_model(
        updated, group_ids=get_group_ids_for_skill(skill_id, db_session)
    )


@admin_router.put("/custom/{skill_id}/bundle")
def replace_custom_skill_bundle(
    skill_id: UUID,
    bundle: UploadFile = File(...),
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> CustomSkillResponse:
    updated = skill_service.replace_admin_custom_skill_bundle(
        skill_id=skill_id,
        bundle_bytes=read_bundle_file(bundle.file),
        filename=bundle.filename,
        user=user,
        db_session=db_session,
    )
    return CustomSkillResponse.from_model(
        updated, group_ids=get_group_ids_for_skill(skill_id, db_session)
    )


@admin_router.put("/custom/{skill_id}/grants")
def replace_custom_skill_grants(
    skill_id: UUID,
    body: GrantsReplace,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> CustomSkillResponse:
    updated = skill_service.replace_admin_custom_skill_grants(
        skill_id=skill_id,
        group_ids=body.group_ids,
        user=user,
        db_session=db_session,
    )
    return CustomSkillResponse.from_model(updated, group_ids=body.group_ids)


@admin_router.delete("/custom/{skill_id}")
def delete_custom_skill(
    skill_id: UUID,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    skill_service.delete_admin_custom_skill(
        skill_id=skill_id,
        user=user,
        db_session=db_session,
    )


@user_router.get("")
def list_skills_for_current_user(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillsList:
    rows = list(list_skills_for_user(user=user, db_session=db_session))
    builtins, customs = _split_rows(rows, db_session, include_grants=False)
    return SkillsList(builtins=builtins, customs=customs)


@user_router.get("/{slug_or_id}")
def fetch_skill_for_current_user(
    slug_or_id: str,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> Annotated[
    BuiltinSkillResponse | CustomSkillResponse, Field(discriminator="source")
]:
    try:
        skill_id: UUID | None = UUID(slug_or_id)
    except ValueError:
        skill_id = None

    found: Skill | None = None
    if skill_id is not None:
        found = fetch_skill_for_user(skill_id, user, db_session)
    if found is None:
        found = fetch_skill_for_user_by_slug(slug_or_id, user, db_session)
    if found is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")

    if found.built_in_skill_id is not None:
        definition = BUILT_IN_SKILLS.get(found.built_in_skill_id)
        if definition is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
        return BuiltinSkillResponse.from_row(found, definition, db_session)
    return CustomSkillResponse.from_model(
        found,
        group_ids=[],
        has_grants=found.id in skill_ids_with_grants([found.id], db_session),
    )


@user_router.get("/{skill_id}/preview")
def preview_skill_for_current_user(
    skill_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillPreviewResponse:
    found = fetch_skill_for_user(skill_id, user, db_session)
    if found is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")

    return _preview_response_for_skill(found)


@user_router.post("/custom")
def create_personal_skill(
    bundle: UploadFile = File(...),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> CustomSkillResponse:
    skill = skill_service.create_personal_skill(
        bundle_bytes=read_bundle_file(bundle.file),
        filename=bundle.filename,
        user=user,
        db_session=db_session,
    )
    return CustomSkillResponse.from_model(skill, group_ids=[])


@user_router.put("/custom/{skill_id}/bundle")
def replace_personal_skill_bundle(
    skill_id: UUID,
    bundle: UploadFile = File(...),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> CustomSkillResponse:
    updated = skill_service.replace_personal_skill_bundle(
        skill_id=skill_id,
        bundle_bytes=read_bundle_file(bundle.file),
        filename=bundle.filename,
        user=user,
        db_session=db_session,
    )
    return CustomSkillResponse.from_model(updated, group_ids=[])


@user_router.patch("/custom/{skill_id}")
def patch_personal_skill(
    skill_id: UUID,
    patch_req: PersonalSkillPatchRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> CustomSkillResponse:
    """Owner toggle for ``enabled``. The skill stays listed for the owner
    while disabled (greyed out) but drops out of their sandbox fileset."""
    updated = skill_service.patch_personal_skill(
        skill_id=skill_id,
        enabled=patch_req.enabled,
        user=user,
        db_session=db_session,
    )
    return CustomSkillResponse.from_model(updated, group_ids=[])


@user_router.delete("/custom/{skill_id}")
def delete_personal_skill(
    skill_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    skill_service.delete_personal_skill(
        skill_id=skill_id,
        user=user,
        db_session=db_session,
    )


def _parse_group_ids(raw: str) -> list[int]:
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "group_ids must be a JSON array of integers",
        )
    if not isinstance(parsed, list) or not all(
        isinstance(g, int) and not isinstance(g, bool) for g in parsed
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "group_ids must be a JSON array of integers",
        )
    return parsed
