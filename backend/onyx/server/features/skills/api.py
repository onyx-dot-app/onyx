"""HTTP surface for the universal Skills primitive.

Admin routes (`/api/admin/skills`) own CRUD for custom (admin-uploaded) skills
and surface the registry of built-in skills. The user route (`/api/skills`)
returns the union of built-ins satisfied for the current tenant and customs
visible to the current user — the forward-looking view a fresh session would
materialize.

DB ops (`onyx.db.skill`) never commit; this layer owns the transaction
boundary and post-commit FileStore cleanup. On any failure between saving a
new bundle blob and committing its row, the route deletes the orphan blob
inline before re-raising. The orphan sweep (§16) is a safety net, not the
primary cleanup path.
"""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.configs.constants import FileOrigin
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.db.skill import create_skill
from onyx.db.skill import delete_skill
from onyx.db.skill import list_skills_for_user
from onyx.db.skill import patch_skill
from onyx.db.skill import replace_skill_bundle
from onyx.db.skill import replace_skill_grants
from onyx.db.utils import UNSET
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.skills.bundle import compute_bundle_sha256
from onyx.skills.bundle import DEFAULT_TOTAL_MAX_BYTES
from onyx.skills.bundle import validate_custom_bundle
from onyx.skills.registry import BuiltinSkillData
from onyx.skills.registry import BuiltinSkillRegistry
from onyx.skills.registry import CustomSkill
from onyx.skills.registry import Skill as RegistrySkill
from onyx.utils.logger import setup_logger

logger = setup_logger()


admin_router = APIRouter(prefix="/admin/skills")
basic_router = APIRouter(prefix="/skills")


# ---------------------------------------------------------------------------
# Response models  (P2.003)
# ---------------------------------------------------------------------------


class BuiltinSkillAdmin(BuiltinSkillData):
    """Admin view: registry's serializable subset + the resolved availability bool.

    `unavailable_reason` is inherited from `BuiltinSkillData`. We override it
    at construct time to `None` when `available is True` (the field answers
    "why is this unavailable", not "what might this need").
    """

    available: bool


class CustomSkillAdmin(CustomSkill):
    """Admin view: registry's `CustomSkill` + admin-only computed fields.

    `CustomSkill` already covers the row's identity, metadata, and
    timestamps. We add only the two fields that aren't on the row itself:
    `bundle_size_bytes` (queried from FileStore) and `granted_group_ids`
    (queried from the `skill__user_group` join table).
    """

    bundle_size_bytes: int | None
    granted_group_ids: list[int]


class SkillsAdminList(BaseModel):
    builtin: list[BuiltinSkillAdmin]
    custom: list[CustomSkillAdmin]


class SkillSummary(RegistrySkill):
    source: Literal["builtin", "custom"]
    skill_id: UUID | None  # set for customs, None for built-ins


class SkillsForUser(BaseModel):
    builtin: list[SkillSummary]
    custom: list[SkillSummary]


class PatchSkillRequest(BaseModel):
    slug: str | None = None
    name: str | None = None
    description: str | None = None
    is_public: bool | None = None
    enabled: bool | None = None


class GrantsRequest(BaseModel):
    group_ids: list[int]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fetch_skill_row_or_404(skill_id: UUID, db_session: Session) -> Skill:
    """Admin-side row fetch returning the ORM model.

    `fetch_skill_for_admin` returns the projected Pydantic model, which is
    missing the timestamps + grants we need for the admin response. We pull
    the ORM row directly so callers can render the full admin shape.
    """
    row = db_session.scalars(select(Skill).where(Skill.id == skill_id)).one_or_none()
    if row is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, f"Skill {skill_id} not found.")
    return row


def _granted_group_ids(skill_id: UUID, db_session: Session) -> list[int]:
    from onyx.db.models import Skill__UserGroup

    rows = db_session.scalars(
        select(Skill__UserGroup.user_group_id).where(
            Skill__UserGroup.skill_id == skill_id
        )
    ).all()
    return sorted(int(row) for row in rows)


def _to_custom_admin(skill_row: Skill, db_session: Session) -> CustomSkillAdmin:
    """Project an ORM row into the admin wire shape.

    `CustomSkillAdmin` inherits `from_attributes=True` via the `Skill` base,
    so Pydantic copies every field straight off the row. We just supply the
    two computed fields that aren't on the row (FileStore size, join-table
    grants).
    """
    file_store = get_default_file_store()
    try:
        size = file_store.get_file_size(skill_row.bundle_file_id, db_session=db_session)
    except Exception:
        # Bundle blob lookup is best-effort metadata; never fail the admin
        # list because the FileStore hiccups.
        size = None
    return CustomSkillAdmin(
        **CustomSkill.model_validate(skill_row).model_dump(),
        bundle_size_bytes=size,
        granted_group_ids=_granted_group_ids(skill_row.id, db_session),
    )


async def _read_capped_bundle(file: UploadFile) -> bytes:
    """Drain the upload, refusing inputs larger than the total cap.

    Reading the whole stream up-front bounds memory and gives the validator
    deterministic bytes. The bundle cap is small (100 MiB by default), so the
    naive approach is fine.
    """
    data = await file.read()
    if len(data) > DEFAULT_TOTAL_MAX_BYTES:
        raise OnyxError(
            OnyxErrorCode.PAYLOAD_TOO_LARGE,
            f"bundle exceeds {DEFAULT_TOTAL_MAX_BYTES // (1024 * 1024)} MiB",
        )
    return data


def _save_bundle_blob(
    bundle_bytes: bytes, filename: str | None, content_type: str | None
) -> str:
    import io

    file_store = get_default_file_store()
    return file_store.save_file(
        content=io.BytesIO(bundle_bytes),
        display_name=filename,
        file_origin=FileOrigin.SKILL_BUNDLE,
        file_type=content_type or "application/zip",
    )


def _delete_blob_silently(file_id: str) -> None:
    """Best-effort blob delete used on post-commit cleanup paths.

    If this fails the orphan sweep (§16) will catch it eventually, so log
    and move on rather than leak a 500 to the admin.
    """
    try:
        get_default_file_store().delete_file(file_id, error_on_missing=False)
    except Exception:
        logger.exception("failed to delete skill bundle blob %s", file_id)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@admin_router.get("")
def list_skills_admin(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillsAdminList:
    registry = BuiltinSkillRegistry.instance()
    builtins: list[BuiltinSkillAdmin] = []
    for skill in registry.list_all():
        available = skill.is_available(db_session)
        builtins.append(
            BuiltinSkillAdmin(
                slug=skill.slug,
                name=skill.name,
                description=skill.description,
                has_template=skill.has_template,
                available=available,
                # Only populated when the skill is unavailable — the field
                # answers "why is this unavailable", not "what does this
                # skill need". When available, the answer is "nothing".
                unavailable_reason=None if available else skill.unavailable_reason,
            )
        )
    custom_rows = db_session.scalars(select(Skill).order_by(Skill.name)).all()
    custom = [_to_custom_admin(row, db_session) for row in custom_rows]
    return SkillsAdminList(builtin=builtins, custom=custom)


@admin_router.post("/custom")
async def create_custom_skill(
    bundle: UploadFile = File(...),
    slug: str = Form(...),
    name: str = Form(...),
    description: str = Form(...),
    is_public: bool = Form(False),
    group_ids: list[int] = Form(default_factory=list),
    user: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> CustomSkillAdmin:
    """Create a custom skill atomically: validate → save blob → row → grants.

    If any step after the blob save fails we delete the orphan blob inline
    before the error propagates. The sweep is the long-tail safety net, not
    the primary cleanup path.
    """
    bundle_bytes = await _read_capped_bundle(bundle)
    validate_custom_bundle(bundle_bytes, slug)
    bundle_sha256 = compute_bundle_sha256(bundle_bytes)

    bundle_file_id = _save_bundle_blob(
        bundle_bytes, bundle.filename, bundle.content_type
    )

    try:
        skill = create_skill(
            slug=slug,
            name=name,
            description=description,
            bundle_file_id=bundle_file_id,
            bundle_sha256=bundle_sha256,
            is_public=is_public,
            author_user_id=user.id,
            db_session=db_session,
        )
        if group_ids:
            replace_skill_grants(skill.id, group_ids, db_session)
        db_session.commit()
    except Exception:
        db_session.rollback()
        _delete_blob_silently(bundle_file_id)
        raise

    row = _fetch_skill_row_or_404(skill.id, db_session)
    return _to_custom_admin(row, db_session)


@admin_router.patch("/custom/{skill_id}")
def patch_custom_skill(
    skill_id: UUID,
    payload: PatchSkillRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> CustomSkillAdmin:
    # Reserved-slug check matches the upload validator so admins can't slip a
    # built-in slug in via rename.
    if payload.slug is not None:
        if payload.slug in BuiltinSkillRegistry.instance().reserved_slugs():
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"slug '{payload.slug}' is reserved",
            )

    patch_skill(
        skill_id=skill_id,
        slug=UNSET if payload.slug is None else payload.slug,
        name=UNSET if payload.name is None else payload.name,
        description=UNSET if payload.description is None else payload.description,
        is_public=UNSET if payload.is_public is None else payload.is_public,
        enabled=UNSET if payload.enabled is None else payload.enabled,
        db_session=db_session,
    )
    db_session.commit()
    row = _fetch_skill_row_or_404(skill_id, db_session)
    return _to_custom_admin(row, db_session)


@admin_router.put("/custom/{skill_id}/bundle")
async def replace_custom_skill_bundle(
    skill_id: UUID,
    bundle: UploadFile = File(...),
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> CustomSkillAdmin:
    """Swap the bundle blob for an existing custom skill.

    Old blob is deleted *after* the DB commit succeeds. If the commit fails
    the new blob is the orphan; if the post-commit delete fails the old blob
    is the orphan. Either way the sweep catches it.
    """
    existing = _fetch_skill_row_or_404(skill_id, db_session)
    slug = existing.slug

    bundle_bytes = await _read_capped_bundle(bundle)
    validate_custom_bundle(bundle_bytes, slug)
    new_sha256 = compute_bundle_sha256(bundle_bytes)

    new_bundle_file_id = _save_bundle_blob(
        bundle_bytes, bundle.filename, bundle.content_type
    )

    try:
        _updated, old_bundle_file_id = replace_skill_bundle(
            skill_id=skill_id,
            new_bundle_file_id=new_bundle_file_id,
            new_bundle_sha256=new_sha256,
            db_session=db_session,
        )
        db_session.commit()
    except Exception:
        db_session.rollback()
        _delete_blob_silently(new_bundle_file_id)
        raise

    if old_bundle_file_id:
        _delete_blob_silently(old_bundle_file_id)

    row = _fetch_skill_row_or_404(skill_id, db_session)
    return _to_custom_admin(row, db_session)


@admin_router.put("/custom/{skill_id}/grants")
def replace_custom_skill_grants(
    skill_id: UUID,
    payload: GrantsRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> CustomSkillAdmin:
    replace_skill_grants(skill_id, payload.group_ids, db_session)
    db_session.commit()
    row = _fetch_skill_row_or_404(skill_id, db_session)
    return _to_custom_admin(row, db_session)


@admin_router.delete("/custom/{skill_id}")
def delete_custom_skill(
    skill_id: UUID,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    """Hard-delete the skill row and its blob.

    Phase 1 chose hard-delete over soft-delete: the bundle blob ID is
    returned by `delete_skill` so we can drop it from the FileStore right
    after the DB commit succeeds. Idempotent — deleting an unknown id is a
    no-op (returns None) and still 204s.
    """
    bundle_file_id = delete_skill(skill_id, db_session)
    db_session.commit()
    if bundle_file_id:
        _delete_blob_silently(bundle_file_id)


# ---------------------------------------------------------------------------
# User endpoint
# ---------------------------------------------------------------------------


@basic_router.get("")
def list_skills_for_current_user(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SkillsForUser:
    """Forward-looking view of skills accessible to the calling user.

    Mirrors what a fresh session would materialize — useful for the future
    user-facing UI and admin previews. Live session content (snapshot
    fidelity) is served separately by the build-feature panel endpoint.
    """
    registry = BuiltinSkillRegistry.instance()
    builtins = [
        SkillSummary(
            slug=skill.slug,
            name=skill.name,
            description=skill.description,
            source="builtin",
            skill_id=None,
        )
        for skill in registry.list_available(db_session)
    ]

    customs: list[SkillSummary] = []
    for skill in list_skills_for_user(user, db_session):
        assert isinstance(skill, CustomSkill)
        customs.append(
            SkillSummary(
                slug=skill.slug,
                name=skill.name,
                description=skill.description,
                source="custom",
                skill_id=skill.id,
            )
        )

    return SkillsForUser(builtin=builtins, custom=customs)
