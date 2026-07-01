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
from onyx.configs.app_configs import MAX_PERSONAL_SKILLS_PER_USER
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.db.skill import affected_user_ids_for_skill
from onyx.db.skill import count_personal_skills_for_user
from onyx.db.skill import create_skill__no_commit
from onyx.db.skill import delete_skill
from onyx.db.skill import fetch_skill_by_id
from onyx.db.skill import fetch_skill_for_edit
from onyx.db.skill import fetch_skill_for_user
from onyx.db.skill import fetch_skill_for_user_by_slug
from onyx.db.skill import get_group_ids_for_skill
from onyx.db.skill import list_skills
from onyx.db.skill import list_skills_for_user
from onyx.db.skill import lock_personal_skills_for_user
from onyx.db.skill import patch_skill
from onyx.db.skill import replace_skill_grants
from onyx.db.skill import skill_ids_with_grants
from onyx.db.skill import SkillAccessPolicy
from onyx.db.skill import SkillPatch
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.skill.models import BuiltinSkillResponse
from onyx.server.features.skill.models import CustomSkillResponse
from onyx.server.features.skill.models import GrantsReplace
from onyx.server.features.skill.models import PersonalSkillPatchRequest
from onyx.server.features.skill.models import SkillPatchRequest
from onyx.server.features.skill.models import SkillPreviewResponse
from onyx.server.features.skill.models import SkillsList
from onyx.server.features.skill.mutation_helpers import ensure_custom_skill
from onyx.server.features.skill.mutation_helpers import ensure_owned_personal_skill
from onyx.server.features.skill.mutation_helpers import ingested_skill_bundle
from onyx.server.features.skill.mutation_helpers import reject_reserved_skill_slug
from onyx.server.features.skill.mutation_helpers import (
    replace_custom_skill_bundle_contents,
)
from onyx.server.features.skill.response_helpers import preview_response_for_skill
from onyx.server.features.skill.response_helpers import split_skill_rows
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.ingest import delete_bundle_blob
from onyx.skills.push import push_skill_to_affected_sandboxes
from onyx.skills.push import push_skills_for_users

admin_router = APIRouter(prefix="/admin/skills")
user_router = APIRouter(prefix="/skills")


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
    builtins, customs = split_skill_rows(rows, db_session, include_grants=True)
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
    return preview_response_for_skill(skill)


@admin_router.post("/custom")
def create_custom_skill(
    is_public: bool = Form(False),
    group_ids: str = Form("[]"),
    bundle: UploadFile = File(...),
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> CustomSkillResponse:
    parsed_group_ids = _parse_group_ids(group_ids)
    reject_reserved_skill_slug(bundle.filename)

    with ingested_skill_bundle(
        bundle_file=bundle.file,
        filename=bundle.filename,
    ) as ingested:
        skill = create_skill__no_commit(
            slug=ingested.slug,
            name=ingested.name,
            description=ingested.description,
            bundle_file_id=ingested.bundle_file_id,
            bundle_sha256=ingested.bundle_sha256,
            is_public=is_public,
            author_user_id=user.id,
            db_session=db_session,
        )
        if parsed_group_ids:
            replace_skill_grants(skill.id, parsed_group_ids, db_session=db_session)
        db_session.commit()

    push_skill_to_affected_sandboxes(skill, db_session)
    return CustomSkillResponse.from_model(skill, group_ids=parsed_group_ids)


@admin_router.patch("/custom/{skill_id}")
def patch_custom_skill(
    skill_id: UUID,
    patch_req: SkillPatchRequest,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> CustomSkillResponse:
    """Toggle ``enabled``/``is_public`` on a custom skill."""
    skill = fetch_skill_for_edit(skill_id, user, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    ensure_custom_skill(skill)

    old_visibility = (skill.public_permission, skill.enabled)
    before_affected = affected_user_ids_for_skill(skill, db_session)

    updated = patch_skill(
        skill_id=skill_id, patch=patch_req.to_domain(), db_session=db_session
    )
    db_session.commit()

    visibility_changed = old_visibility != (updated.public_permission, updated.enabled)
    if visibility_changed:
        after_affected = affected_user_ids_for_skill(updated, db_session)
        push_skills_for_users(before_affected | after_affected, db_session)

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
    skill = fetch_skill_for_edit(skill_id, user, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    ensure_custom_skill(skill)

    updated = replace_custom_skill_bundle_contents(
        skill=skill,
        bundle_file=bundle.file,
        filename=bundle.filename,
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
    skill = fetch_skill_for_edit(skill_id, user, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    ensure_custom_skill(skill)

    before_affected = affected_user_ids_for_skill(skill, db_session)

    replace_skill_grants(skill_id, body.group_ids, db_session=db_session)
    db_session.commit()

    updated = fetch_skill_by_id(skill_id, db_session)
    if updated is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    after_affected = affected_user_ids_for_skill(updated, db_session)
    push_skills_for_users(before_affected | after_affected, db_session)

    return CustomSkillResponse.from_model(updated, group_ids=body.group_ids)


@admin_router.delete("/custom/{skill_id}")
def delete_custom_skill(
    skill_id: UUID,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    skill = fetch_skill_for_edit(skill_id, user, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    ensure_custom_skill(skill)

    affected = affected_user_ids_for_skill(skill, db_session)
    old_file_id = delete_skill(skill_id, db_session)
    db_session.commit()

    push_skills_for_users(affected, db_session)
    if old_file_id is not None:
        delete_bundle_blob(get_default_file_store(), old_file_id)


@user_router.get("")
def list_skills_for_current_user(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillsList:
    rows = list(list_skills_for_user(user=user, db_session=db_session))
    builtins, customs = split_skill_rows(rows, db_session, include_grants=False)
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

    return preview_response_for_skill(found)


@user_router.post("/custom")
def create_personal_skill(
    bundle: UploadFile = File(...),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> CustomSkillResponse:
    lock_personal_skills_for_user(user.id, db_session)
    if (
        count_personal_skills_for_user(user.id, db_session)
        >= MAX_PERSONAL_SKILLS_PER_USER
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"You have reached the limit of {MAX_PERSONAL_SKILLS_PER_USER} "
            "personal skills. Delete one before creating another.",
        )

    reject_reserved_skill_slug(bundle.filename)

    with ingested_skill_bundle(
        bundle_file=bundle.file,
        filename=bundle.filename,
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
    return CustomSkillResponse.from_model(skill, group_ids=[])


@user_router.put("/custom/{skill_id}/bundle")
def replace_personal_skill_bundle(
    skill_id: UUID,
    bundle: UploadFile = File(...),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> CustomSkillResponse:
    # fetch_skill_by_id bypasses the enabled filter on purpose: an
    # admin-disabled personal skill must stay mutable by its owner.
    skill = fetch_skill_by_id(skill_id, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    ensure_owned_personal_skill(skill, user, db_session)

    updated = replace_custom_skill_bundle_contents(
        skill=skill,
        bundle_file=bundle.file,
        filename=bundle.filename,
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
    skill = fetch_skill_by_id(skill_id, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    ensure_owned_personal_skill(skill, user, db_session)

    enabled_changed = skill.enabled != patch_req.enabled
    before_affected = affected_user_ids_for_skill(skill, db_session)
    updated = patch_skill(
        skill_id=skill_id,
        patch=SkillPatch(enabled=patch_req.enabled),
        db_session=db_session,
    )
    db_session.commit()

    if enabled_changed:
        after_affected = affected_user_ids_for_skill(updated, db_session)
        push_skills_for_users(before_affected | after_affected, db_session)
    return CustomSkillResponse.from_model(updated, group_ids=[])


@user_router.delete("/custom/{skill_id}")
def delete_personal_skill(
    skill_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    skill = fetch_skill_by_id(skill_id, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    ensure_owned_personal_skill(skill, user, db_session)

    affected = affected_user_ids_for_skill(skill, db_session)
    old_file_id = delete_skill(skill_id, db_session)
    db_session.commit()

    push_skills_for_users(affected, db_session)
    if old_file_id is not None:
        delete_bundle_blob(get_default_file_store(), old_file_id)


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
