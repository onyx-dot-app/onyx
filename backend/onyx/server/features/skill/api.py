import json
from typing import Annotated
from typing import Final
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
from onyx.db.skill import fetch_skill_for_user
from onyx.db.skill import fetch_skill_for_user_by_slug
from onyx.db.skill import get_group_ids_for_skill
from onyx.db.skill import list_skills_for_admin
from onyx.db.skill import list_skills_for_user
from onyx.db.skill import lock_personal_skills_for_user
from onyx.db.skill import patch_skill
from onyx.db.skill import replace_skill_bundle
from onyx.db.skill import replace_skill_grants
from onyx.db.skill import skill_ids_with_grants
from onyx.db.skill import SkillPatch
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.skill.models import BuiltinSkillResponse
from onyx.server.features.skill.models import CustomSkillResponse
from onyx.server.features.skill.models import GrantsReplace
from onyx.server.features.skill.models import PersonalSkillPatchRequest
from onyx.server.features.skill.models import SkillPatchRequest
from onyx.server.features.skill.models import SkillsList
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.built_in import EXTERNAL_APP_BUILT_IN_SKILL_IDS
from onyx.skills.bundle import DEFAULT_TOTAL_MAX_BYTES
from onyx.skills.bundle import slug_from_filename
from onyx.skills.ingest import delete_bundle_blob
from onyx.skills.ingest import ingest_skill_bundle
from onyx.skills.push import push_skill_to_affected_sandboxes
from onyx.skills.push import push_skills_for_users
from onyx.utils.logger import setup_logger

logger = setup_logger()

admin_router = APIRouter(prefix="/admin/skills")
user_router = APIRouter(prefix="/skills")

# Built-in slugs plus external-app provider slugs (rows created on demand by
# slug — a user-claimed slug would block the org from connecting that app).
_RESERVED_SKILL_SLUGS: Final[frozenset[str]] = frozenset(BUILT_IN_SKILLS) | frozenset(
    EXTERNAL_APP_BUILT_IN_SKILL_IDS.values()
)


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
    granted_skill_ids: set[UUID] = set()
    if not include_grants:
        custom_ids = [s.id for s in rows if s.built_in_skill_id is None]
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
            customs.append(CustomSkillResponse.from_model(skill, group_ids=group_ids))
        else:
            customs.append(
                CustomSkillResponse.from_model(
                    skill,
                    group_ids=[],
                    has_grants=skill.id in granted_skill_ids,
                )
            )

    return builtins, customs


def _ensure_custom(skill: Skill) -> None:
    """Block any mutation on a built-in skill row.

    Built-ins are codified, always-on, always-public; admins cannot
    rename, disable, share, replace, or delete them. The check
    discriminates on ``built_in_skill_id``."""
    if skill.built_in_skill_id is not None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Skill '{skill.slug}' is a built-in and cannot be modified.",
        )


def _read_bundle_upload(bundle: UploadFile) -> bytes:
    """Read an uploaded bundle without buffering an arbitrarily large body —
    nginx allows multi-GB uploads, and these endpoints are open to all users."""
    data = bundle.file.read(DEFAULT_TOTAL_MAX_BYTES + 1)
    if len(data) > DEFAULT_TOTAL_MAX_BYTES:
        raise OnyxError(
            OnyxErrorCode.PAYLOAD_TOO_LARGE,
            f"Skill bundle exceeds the {DEFAULT_TOTAL_MAX_BYTES} byte limit.",
        )
    return data


def _reject_reserved_slug(bundle: UploadFile) -> None:
    """Reject a bundle whose slug collides with a built-in or external-app slug,
    before any blob is written. Applies to both admin and personal creation — a
    reserved slug would block the org from connecting that app regardless of who
    claims it."""
    slug = slug_from_filename(bundle.filename)
    if slug in _RESERVED_SKILL_SLUGS:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, f"slug '{slug}' is reserved")


def _ensure_owned_personal(skill: Skill, user: User, db_session: Session) -> None:
    """Gate user-endpoint mutations to the caller's own personal skills.

    Non-authors get 404 (they shouldn't learn the skill exists); the
    author of a promoted skill (public or grants-shared) gets 403 — it's
    org-managed now."""
    _ensure_custom(skill)
    if skill.author_user_id != user.id:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    if skill.is_public or get_group_ids_for_skill(skill.id, db_session):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "This skill is managed by your organization and can no longer "
            "be modified through personal skill endpoints.",
        )


@admin_router.get("")
def list_skills_admin(
    _: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> SkillsList:
    rows = list(list_skills_for_admin(db_session=db_session))
    builtins, customs = _split_rows(rows, db_session, include_grants=True)
    return SkillsList(builtins=builtins, customs=customs)


@admin_router.post("/custom")
def create_custom_skill(
    is_public: bool = Form(False),
    group_ids: str = Form("[]"),
    bundle: UploadFile = File(...),
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> CustomSkillResponse:
    parsed_group_ids = _parse_group_ids(group_ids)
    _reject_reserved_slug(bundle)

    file_store = get_default_file_store()
    ingested = ingest_skill_bundle(
        _read_bundle_upload(bundle), bundle.filename, file_store
    )

    try:
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
    except Exception:
        delete_bundle_blob(file_store, ingested.bundle_file_id)
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
    """Toggle ``enabled``/``is_public`` on a custom skill. Built-in
    rows are rejected — their identity and lifecycle are codified."""
    domain_patch = patch_req.to_domain()

    skill = fetch_skill_by_id(skill_id, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    _ensure_custom(skill)

    # SQLAlchemy identity map mutates in place; snapshot before patch.
    old_is_public = skill.is_public
    old_enabled = skill.enabled
    before_affected = affected_user_ids_for_skill(skill, db_session)

    updated = patch_skill(skill_id=skill_id, patch=domain_patch, db_session=db_session)
    db_session.commit()

    visibility_changed = (
        old_is_public != updated.is_public or old_enabled != updated.enabled
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
    skill = fetch_skill_by_id(skill_id, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    _ensure_custom(skill)

    file_store = get_default_file_store()
    ingested = ingest_skill_bundle(
        _read_bundle_upload(bundle), bundle.filename, file_store, slug=skill.slug
    )

    try:
        updated, old_file_id = replace_skill_bundle(
            skill_id=skill_id,
            new_bundle_file_id=ingested.bundle_file_id,
            new_bundle_sha256=ingested.bundle_sha256,
            new_name=ingested.name,
            new_description=ingested.description,
            db_session=db_session,
        )
        db_session.commit()
    except Exception:
        delete_bundle_blob(file_store, ingested.bundle_file_id)
        raise

    push_skill_to_affected_sandboxes(updated, db_session)
    delete_bundle_blob(file_store, old_file_id)
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
    skill = fetch_skill_by_id(skill_id, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    _ensure_custom(skill)

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
    _: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    skill = fetch_skill_by_id(skill_id, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    _ensure_custom(skill)

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
        has_grants=bool(get_group_ids_for_skill(found.id, db_session)),
    )


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

    # Reject reserved slugs up front so we never write a bundle blob for one.
    _reject_reserved_slug(bundle)

    file_store = get_default_file_store()
    ingested = ingest_skill_bundle(
        _read_bundle_upload(bundle), bundle.filename, file_store
    )

    try:
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
    except Exception:
        delete_bundle_blob(file_store, ingested.bundle_file_id)
        raise

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
    _ensure_owned_personal(skill, user, db_session)

    file_store = get_default_file_store()
    ingested = ingest_skill_bundle(
        _read_bundle_upload(bundle), bundle.filename, file_store, slug=skill.slug
    )

    try:
        updated, old_file_id = replace_skill_bundle(
            skill_id=skill_id,
            new_bundle_file_id=ingested.bundle_file_id,
            new_bundle_sha256=ingested.bundle_sha256,
            new_name=ingested.name,
            new_description=ingested.description,
            db_session=db_session,
        )
        db_session.commit()
    except Exception:
        delete_bundle_blob(file_store, ingested.bundle_file_id)
        raise

    push_skill_to_affected_sandboxes(updated, db_session)
    delete_bundle_blob(file_store, old_file_id)
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
    _ensure_owned_personal(skill, user, db_session)

    before_affected = affected_user_ids_for_skill(skill, db_session)
    updated = patch_skill(
        skill_id=skill_id,
        patch=SkillPatch(enabled=patch_req.enabled),
        db_session=db_session,
    )
    db_session.commit()

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
    _ensure_owned_personal(skill, user, db_session)

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
