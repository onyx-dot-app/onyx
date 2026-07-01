from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import UploadFile
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.auth.users import is_user_curator_or_admin
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
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
from onyx.server.features.skill.mutation_helpers import create_custom_skill_for_user
from onyx.server.features.skill.mutation_helpers import delete_custom_skill_for_user
from onyx.server.features.skill.mutation_helpers import get_editable_custom_skill
from onyx.server.features.skill.mutation_helpers import patch_custom_skill_for_user
from onyx.server.features.skill.mutation_helpers import (
    replace_custom_skill_bundle_for_user,
)
from onyx.server.features.skill.mutation_helpers import (
    transfer_custom_skill_ownership_for_user,
)
from onyx.server.features.skill.mutation_helpers import (
    update_custom_skill_shares_for_user,
)
from onyx.server.features.skill.response_helpers import custom_skill_response_for_user
from onyx.server.features.skill.response_helpers import skill_preview_response
from onyx.server.features.skill.response_helpers import skill_response_for_user
from onyx.server.features.skill.response_helpers import skills_list_response_for_user
from onyx.skills.content import read_custom_skill_bundle_instructions

user_router = APIRouter(prefix="/skills")


@user_router.get("")
def list_skills_for_current_user(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillsList:
    rows = list_skills(
        policy=SkillAccessPolicy.VIEW,
        user=user,
        db_session=db_session,
    )
    return skills_list_response_for_user(list(rows), user, db_session)


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
    return skill_response_for_user(
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
    return skill_preview_response(skill)


@user_router.post("/custom")
def create_custom_skill(
    bundle: UploadFile = File(...),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    skill = create_custom_skill_for_user(
        bundle_file=bundle.file,
        filename=bundle.filename,
        user=user,
        db_session=db_session,
    )
    return custom_skill_response_for_user(
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
    response = custom_skill_response_for_user(
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
        bundle_file=bundle.file,
        filename=bundle.filename,
        user=user,
        db_session=db_session,
    )
    return custom_skill_response_for_user(
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
    return custom_skill_response_for_user(
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
    return custom_skill_response_for_user(
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
    return custom_skill_response_for_user(
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
