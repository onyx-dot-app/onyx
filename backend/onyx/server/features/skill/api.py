import io
import json
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import UploadFile
from sqlalchemy.orm import Session

from onyx.auth.permissions import Permission
from onyx.auth.permissions import require_permission
from onyx.auth.users import current_curator_or_admin_user
from onyx.configs.constants import FileOrigin
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.db.skill import affected_user_ids_for_skill
from onyx.db.skill import create_skill
from onyx.db.skill import delete_skill
from onyx.db.skill import fetch_skill_for_admin
from onyx.db.skill import get_group_ids_for_skill
from onyx.db.skill import list_skills_for_admin
from onyx.db.skill import list_skills_for_user
from onyx.db.skill import patch_skill
from onyx.db.skill import replace_skill_bundle
from onyx.db.skill import replace_skill_grants
from onyx.db.utils import UnsetType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import FileStore
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.skill.models import BuiltinSkillResponse
from onyx.server.features.skill.models import CustomSkillResponse
from onyx.server.features.skill.models import GrantsReplace
from onyx.server.features.skill.models import SkillPatchRequest
from onyx.server.features.skill.models import SkillsList
from onyx.skills.bundle import check_slug
from onyx.skills.bundle import compute_bundle_sha256
from onyx.skills.bundle import validate_custom_bundle
from onyx.skills.push import push_skill_to_affected_sandboxes
from onyx.skills.push import push_skills_for_users
from onyx.skills.registry import BuiltinSkillRegistry
from onyx.utils.logger import setup_logger

logger = setup_logger()

admin_router = APIRouter(prefix="/admin/skills")
user_router = APIRouter(prefix="/skills")


@admin_router.get("")
def list_skills_admin(
    _: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> SkillsList:
    registry = BuiltinSkillRegistry.instance()
    builtins = [
        BuiltinSkillResponse.from_builtin(b, db_session) for b in registry.list_all()
    ]
    customs = list_skills_for_admin(db_session=db_session)
    return SkillsList(
        builtins=builtins,
        customs=[
            CustomSkillResponse.from_model(
                c, group_ids=get_group_ids_for_skill(c.id, db_session)
            )
            for c in customs
        ],
    )


@admin_router.post("/custom")
def create_custom_skill(
    slug: str = Form(...),
    name: str = Form(...),
    description: str = Form(...),
    is_public: bool = Form(False),
    group_ids: str = Form("[]"),
    bundle: UploadFile = File(...),
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> CustomSkillResponse:
    bundle_bytes = bundle.file.read()
    validate_custom_bundle(bundle_bytes, slug=slug)
    sha = compute_bundle_sha256(bundle_bytes)
    parsed_group_ids = _parse_group_ids(group_ids)

    file_store = get_default_file_store()
    bundle_file_id = file_store.save_file(
        content=io.BytesIO(bundle_bytes),
        display_name=f"{slug}.zip",
        file_origin=FileOrigin.SKILL_BUNDLE,
        file_type="application/zip",
    )

    try:
        skill = create_skill(
            slug=slug,
            name=name,
            description=description,
            bundle_file_id=bundle_file_id,
            bundle_sha256=sha,
            is_public=is_public,
            author_user_id=user.id,
            db_session=db_session,
        )
        if parsed_group_ids:
            replace_skill_grants(skill.id, parsed_group_ids, db_session=db_session)
        db_session.commit()
    except Exception:
        _delete_old_bundle(file_store, bundle_file_id)
        raise

    push_skill_to_affected_sandboxes(skill, db_session)
    return CustomSkillResponse.from_model(skill, group_ids=parsed_group_ids)


@admin_router.patch("/custom/{skill_id}")
def patch_custom_skill(
    skill_id: UUID,
    patch_req: SkillPatchRequest,
    _: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> CustomSkillResponse:
    domain_patch = patch_req.to_domain()

    skill = fetch_skill_for_admin(skill_id, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")

    if not isinstance(domain_patch.slug, UnsetType):
        check_slug(domain_patch.slug)
        if domain_patch.slug in BuiltinSkillRegistry.instance().reserved_slugs():
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT, "Slug reserved by a built-in skill"
            )

    # Snapshot before patch — SQLAlchemy identity map means the ORM object
    # is mutated in-place by patch_skill, so we can't compare before/after.
    old_is_public = skill.is_public
    old_enabled = skill.enabled
    old_slug = skill.slug
    before_affected = affected_user_ids_for_skill(skill, db_session)

    updated = patch_skill(skill_id=skill_id, patch=domain_patch, db_session=db_session)
    db_session.commit()

    visibility_changed = (
        old_is_public != updated.is_public
        or old_enabled != updated.enabled
        or old_slug != updated.slug
    )
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
    _: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> CustomSkillResponse:
    skill = fetch_skill_for_admin(skill_id, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")

    bundle_bytes = bundle.file.read()
    validate_custom_bundle(bundle_bytes, slug=skill.slug)
    sha = compute_bundle_sha256(bundle_bytes)

    file_store = get_default_file_store()
    new_file_id = file_store.save_file(
        content=io.BytesIO(bundle_bytes),
        display_name=f"{skill.slug}.zip",
        file_origin=FileOrigin.SKILL_BUNDLE,
        file_type="application/zip",
    )

    try:
        updated, old_file_id = replace_skill_bundle(
            skill_id=skill_id,
            new_bundle_file_id=new_file_id,
            new_bundle_sha256=sha,
            db_session=db_session,
        )
        db_session.commit()
    except Exception:
        _delete_old_bundle(file_store, new_file_id)
        raise

    push_skill_to_affected_sandboxes(updated, db_session)
    _delete_old_bundle(file_store, old_file_id)
    return CustomSkillResponse.from_model(
        updated, group_ids=get_group_ids_for_skill(skill_id, db_session)
    )


@admin_router.put("/custom/{skill_id}/grants")
def replace_custom_skill_grants(
    skill_id: UUID,
    body: GrantsReplace,
    _: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> CustomSkillResponse:
    skill = fetch_skill_for_admin(skill_id, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")

    before_affected = affected_user_ids_for_skill(skill, db_session)

    replace_skill_grants(skill_id, body.group_ids, db_session=db_session)
    db_session.commit()

    updated = fetch_skill_for_admin(skill_id, db_session)
    if updated is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    after_affected = affected_user_ids_for_skill(updated, db_session)
    push_skills_for_users(before_affected | after_affected, db_session)

    return CustomSkillResponse.from_model(updated, group_ids=body.group_ids)


@admin_router.delete("/custom/{skill_id}")
def delete_custom_skill(
    skill_id: UUID,
    _: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    skill = fetch_skill_for_admin(skill_id, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")

    affected = affected_user_ids_for_skill(skill, db_session)
    old_file_id = delete_skill(skill_id, db_session)
    db_session.commit()

    push_skills_for_users(affected, db_session)
    if old_file_id is not None:
        _delete_old_bundle(get_default_file_store(), old_file_id)


@user_router.get("")
def list_skills_for_current_user(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillsList:
    registry = BuiltinSkillRegistry.instance()
    builtins = [
        BuiltinSkillResponse.from_builtin(b, db_session)
        for b in registry.list_available(db_session)
    ]
    customs = list_skills_for_user(user=user, db_session=db_session)
    return SkillsList(
        builtins=builtins,
        customs=[CustomSkillResponse.from_model(c, group_ids=[]) for c in customs],
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


def _delete_old_bundle(file_store: FileStore, file_id: str) -> None:
    try:
        file_store.delete_file(file_id, error_on_missing=False)
    except Exception:
        logger.warning("Failed to delete old bundle blob %s", file_id, exc_info=True)
