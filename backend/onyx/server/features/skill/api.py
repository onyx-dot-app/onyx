from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import UploadFile
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.auth.schemas import UserRole
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.db.skill import affected_user_ids_for_skill
from onyx.db.skill import create_skill__no_commit
from onyx.db.skill import delete_skill
from onyx.db.skill import fetch_skill
from onyx.db.skill import list_skills
from onyx.db.skill import replace_skill_bundle
from onyx.db.skill import SkillAccessPolicy
from onyx.db.skill import update_skill_fields
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.skill.models import SkillPatchRequest
from onyx.server.features.skill.models import SkillPreviewResponse
from onyx.server.features.skill.models import SkillResponse
from onyx.server.features.skill.models import SkillsList
from onyx.server.features.skill.response_helpers import skill_preview_response
from onyx.server.features.skill.response_helpers import skill_response_for_user
from onyx.server.features.skill.response_helpers import skills_list_response_for_user
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.built_in import EXTERNAL_APP_BUILT_IN_SKILL_IDS
from onyx.skills.bundle import read_bundle_file
from onyx.skills.bundle import slug_from_filename
from onyx.skills.ingest import delete_bundle_blob
from onyx.skills.ingest import ingested_skill_bundle
from onyx.skills.push import push_skill_to_affected_sandboxes
from onyx.skills.push import push_skills_for_users

user_router = APIRouter(prefix="/skills")


def _ensure_can_edit_org_visibility(skill: Skill, user: User) -> None:
    if skill.author_user_id == user.id:
        return
    if user.role == UserRole.ADMIN:
        return
    raise OnyxError(
        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
        "You do not have permission to change organization-wide skill access.",
    )


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
    return skills_list_response_for_user(rows, user, db_session)


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
    return skill_response_for_user(skill, user, db_session)


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
    slug = slug_from_filename(bundle.filename)
    reserved_slugs = frozenset(BUILT_IN_SKILLS) | frozenset(
        EXTERNAL_APP_BUILT_IN_SKILL_IDS.values()
    )
    if slug in reserved_slugs:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, f"slug '{slug}' is reserved")

    file_store = get_default_file_store()
    with ingested_skill_bundle(
        read_bundle_file(bundle.file),
        bundle.filename,
        file_store,
    ) as ingested:
        skill = create_skill__no_commit(
            slug=ingested.slug,
            name=ingested.name,
            description=ingested.description,
            bundle_file_id=ingested.bundle_file_id,
            bundle_sha256=ingested.bundle_sha256,
            is_public=False,
            author_user_id=user.id,
            db_session=db_session,
        )
        db_session.commit()

    push_skill_to_affected_sandboxes(skill, db_session)
    return skill_response_for_user(
        skill,
        user,
        db_session,
        include_share_details=True,
    )


@user_router.put("/custom/{skill_id}/bundle")
def replace_current_user_skill_bundle(
    skill_id: UUID,
    bundle: UploadFile = File(...),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillResponse:
    skill = fetch_skill(
        skill_id,
        policy=SkillAccessPolicy.EDIT,
        user=user,
        db_session=db_session,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")

    file_store = get_default_file_store()
    with ingested_skill_bundle(
        read_bundle_file(bundle.file),
        bundle.filename,
        file_store,
        slug=skill.slug,
    ) as ingested:
        old_file_id = replace_skill_bundle(
            skill=skill,
            new_bundle_file_id=ingested.bundle_file_id,
            new_bundle_sha256=ingested.bundle_sha256,
            new_name=ingested.name,
            new_description=ingested.description,
            db_session=db_session,
        )
        db_session.commit()

    db_session.expire(skill)
    push_skill_to_affected_sandboxes(skill, db_session)
    delete_bundle_blob(file_store, old_file_id)
    return skill_response_for_user(
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
    skill = fetch_skill(
        skill_id,
        policy=SkillAccessPolicy.EDIT,
        user=user,
        db_session=db_session,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    if "public_permission" in patch_req.model_fields_set:
        _ensure_can_edit_org_visibility(skill, user)

    if not patch_req.has_db_field_update:
        return skill_response_for_user(
            skill,
            user,
            db_session,
            include_share_details=True,
        )

    old_visibility = (skill.public_permission, skill.enabled)
    before_affected = affected_user_ids_for_skill(skill, db_session)

    public_permission = (
        patch_req.public_permission
        if "public_permission" in patch_req.model_fields_set
        else None
    )
    is_public = (
        public_permission is not None
        if "public_permission" in patch_req.model_fields_set
        else None
    )
    enabled = patch_req.enabled if "enabled" in patch_req.model_fields_set else None
    update_skill_fields(
        skill=skill,
        is_public=is_public,
        public_permission=public_permission,
        enabled=enabled,
        db_session=db_session,
    )

    db_session.commit()
    db_session.expire(skill)
    visibility_changed = old_visibility != (
        skill.public_permission,
        skill.enabled,
    )
    if visibility_changed:
        after_affected = affected_user_ids_for_skill(skill, db_session)
        push_skills_for_users(before_affected | after_affected, db_session)

    return skill_response_for_user(
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
    skill = fetch_skill(
        skill_id,
        policy=SkillAccessPolicy.EDIT,
        user=user,
        db_session=db_session,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")

    affected = affected_user_ids_for_skill(skill, db_session)
    old_file_id = delete_skill(skill, db_session)
    db_session.commit()

    push_skills_for_users(affected, db_session)
    if old_file_id is not None:
        delete_bundle_blob(get_default_file_store(), old_file_id)
