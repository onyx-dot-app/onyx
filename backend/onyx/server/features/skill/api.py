from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import UploadFile
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.auth.schemas import UserRole
from onyx.auth.users import is_user_curator_or_admin
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.db.persona_sharing import get_curated_user_group_ids_for_user
from onyx.db.persona_sharing import get_user_group_ids_for_user
from onyx.db.skill import fetch_skill
from onyx.db.skill import list_skills
from onyx.db.skill import SkillAccessPolicy
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill.models import SkillEditableDetailResponse
from onyx.server.features.skill.models import SkillPatchRequest
from onyx.server.features.skill.models import SkillPreviewResponse
from onyx.server.features.skill.models import SkillResponse
from onyx.server.features.skill.models import SkillShareRequest
from onyx.server.features.skill.models import SkillsList
from onyx.server.features.skill.models import TransferSkillOwnershipRequest
from onyx.server.features.skill.service import create_custom_skill_for_user
from onyx.server.features.skill.service import delete_custom_skill_for_user
from onyx.server.features.skill.service import get_editable_custom_skill
from onyx.server.features.skill.service import patch_custom_skill_for_user
from onyx.server.features.skill.service import replace_custom_skill_bundle_for_user
from onyx.server.features.skill.service import transfer_custom_skill_ownership_for_user
from onyx.server.features.skill.service import update_custom_skill_shares_for_user
from onyx.server.features.skill.service import user_permission_for_skill
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.bundle import read_bundle_file
from onyx.skills.content import read_builtin_skill_instructions
from onyx.skills.content import read_custom_skill_bundle_instructions
from onyx.utils.logger import setup_logger

user_router = APIRouter(prefix="/skills")

logger = setup_logger()


def _custom_response_for_user(
    skill: Skill,
    user: User,
    db_session: Session,
    *,
    user_group_ids: set[int] | None = None,
    curated_user_group_ids: set[int] | None = None,
    include_share_details: bool = False,
) -> SkillResponse:
    if user_group_ids is None:
        user_group_ids = get_user_group_ids_for_user(db_session, user.id)
    if curated_user_group_ids is None and user.role == UserRole.CURATOR:
        curated_user_group_ids = get_curated_user_group_ids_for_user(
            db_session, user.id
        )
    user_permission = user_permission_for_skill(
        skill,
        user,
        user_group_ids,
        curated_user_group_ids,
    )
    return SkillResponse.from_custom(
        skill,
        user_permission=user_permission,
        include_share_details=include_share_details,
    )


@user_router.get("")
def list_skills_for_current_user(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillsList:
    is_curator_or_admin = is_user_curator_or_admin(user)
    rows = list_skills(
        policy=SkillAccessPolicy.VIEW,
        user=user,
        db_session=db_session,
    )

    builtins: list[SkillResponse] = []
    customs: list[SkillResponse] = []
    include_share_details = is_curator_or_admin
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
            _custom_response_for_user(
                skill,
                user,
                db_session,
                user_group_ids=user_group_ids,
                curated_user_group_ids=curated_user_group_ids,
                include_share_details=include_share_details,
            )
        )

    return SkillsList(builtins=builtins, customs=customs)


@user_router.get("/{skill_id}")
def fetch_skill_for_current_user(
    skill_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    skill = fetch_skill(
        skill_id,
        policy=SkillAccessPolicy.VIEW,
        user=user,
        db_session=db_session,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    if skill.built_in_skill_id is not None:
        definition = BUILT_IN_SKILLS.get(skill.built_in_skill_id)
        if definition is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
        return SkillResponse.from_builtin(skill, definition, db_session)

    return _custom_response_for_user(
        skill,
        user,
        db_session,
        include_share_details=is_user_curator_or_admin(user),
    )


@user_router.get("/{skill_id}/preview")
def preview_skill_for_current_user(
    skill_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillPreviewResponse:
    skill = fetch_skill(
        skill_id,
        policy=SkillAccessPolicy.VIEW,
        user=user,
        db_session=db_session,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
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


@user_router.post("/custom")
def create_custom_skill(
    bundle: UploadFile = File(...),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    skill = create_custom_skill_for_user(
        bundle_bytes=read_bundle_file(bundle.file),
        filename=bundle.filename,
        user=user,
        db_session=db_session,
    )
    return _custom_response_for_user(
        skill,
        user,
        db_session,
        include_share_details=True,
    )


@user_router.get("/custom/{skill_id}/edit")
def fetch_custom_skill_for_edit(
    skill_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillEditableDetailResponse:
    skill = get_editable_custom_skill(skill_id, user, db_session)
    response = _custom_response_for_user(
        skill,
        user,
        db_session,
        include_share_details=True,
    )
    return SkillEditableDetailResponse(
        **response.model_dump(),
        instructions_markdown=read_custom_skill_bundle_instructions(skill),
    )


@user_router.put("/custom/{skill_id}/bundle")
def replace_current_user_skill_bundle(
    skill_id: UUID,
    bundle: UploadFile = File(...),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    skill = replace_custom_skill_bundle_for_user(
        skill_id=skill_id,
        bundle_bytes=read_bundle_file(bundle.file),
        filename=bundle.filename,
        user=user,
        db_session=db_session,
    )
    return _custom_response_for_user(
        skill,
        user,
        db_session,
        include_share_details=True,
    )


@user_router.patch("/custom/{skill_id}")
def patch_current_user_skill(
    skill_id: UUID,
    patch_req: SkillPatchRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    skill = patch_custom_skill_for_user(
        skill_id=skill_id,
        patch=patch_req,
        user=user,
        db_session=db_session,
    )
    return _custom_response_for_user(
        skill,
        user,
        db_session,
        include_share_details=True,
    )


@user_router.patch("/custom/{skill_id}/share")
def share_current_user_skill(
    skill_id: UUID,
    share_req: SkillShareRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    skill = update_custom_skill_shares_for_user(
        skill_id=skill_id,
        share=share_req,
        user=user,
        db_session=db_session,
    )
    return _custom_response_for_user(
        skill,
        user,
        db_session,
        include_share_details=True,
    )


@user_router.post("/custom/{skill_id}/transfer-ownership")
def transfer_current_user_skill_ownership(
    skill_id: UUID,
    transfer_req: TransferSkillOwnershipRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    skill = transfer_custom_skill_ownership_for_user(
        skill_id=skill_id,
        transfer=transfer_req,
        user=user,
        db_session=db_session,
    )
    return _custom_response_for_user(
        skill,
        user,
        db_session,
        include_share_details=True,
    )


@user_router.delete("/custom/{skill_id}")
def delete_current_user_skill(
    skill_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    delete_custom_skill_for_user(skill_id=skill_id, user=user, db_session=db_session)
