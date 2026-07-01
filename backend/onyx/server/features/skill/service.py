from typing import BinaryIO
from typing import Final
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.configs.app_configs import MAX_PERSONAL_SKILLS_PER_USER
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.db.skill import affected_user_ids_for_skill
from onyx.db.skill import count_personal_skills_for_user
from onyx.db.skill import create_skill__no_commit
from onyx.db.skill import delete_skill
from onyx.db.skill import fetch_skill_by_id
from onyx.db.skill import fetch_skill_for_edit
from onyx.db.skill import lock_personal_skills_for_user
from onyx.db.skill import patch_skill
from onyx.db.skill import replace_skill_bundle
from onyx.db.skill import replace_skill_grants
from onyx.db.skill import skill_ids_with_grants
from onyx.db.skill import SkillPatch
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.built_in import EXTERNAL_APP_BUILT_IN_SKILL_IDS
from onyx.skills.bundle import read_bundle_file
from onyx.skills.bundle import slug_from_filename
from onyx.skills.ingest import delete_bundle_blob
from onyx.skills.ingest import ingest_skill_bundle
from onyx.skills.push import push_skill_to_affected_sandboxes
from onyx.skills.push import push_skills_for_users

# Built-in slugs plus external-app provider slugs (rows created on demand by
# slug — a user-claimed slug would block the org from connecting that app).
_RESERVED_SKILL_SLUGS: Final[frozenset[str]] = frozenset(BUILT_IN_SKILLS) | frozenset(
    EXTERNAL_APP_BUILT_IN_SKILL_IDS.values()
)


def ensure_custom_skill(skill: Skill) -> None:
    """Block any mutation on a built-in skill row."""
    if skill.built_in_skill_id is not None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Skill '{skill.slug}' is a built-in and cannot be modified.",
        )


def reject_reserved_skill_slug(filename: str | None) -> None:
    """Reject a bundle whose slug collides with codified skill identifiers."""
    slug = slug_from_filename(filename)
    if slug in _RESERVED_SKILL_SLUGS:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, f"slug '{slug}' is reserved")


def ensure_owned_personal_skill(
    skill: Skill,
    user: User,
    db_session: Session,
) -> None:
    """Gate user-endpoint mutations to the caller's own personal skills."""
    ensure_custom_skill(skill)
    if skill.author_user_id != user.id:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    if skill.public_permission is not None or skill_ids_with_grants(
        [skill.id], db_session
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "This skill is managed by your organization and can no longer "
            "be modified through personal skill endpoints.",
        )


def create_admin_custom_skill(
    *,
    bundle_file: BinaryIO,
    filename: str | None,
    is_public: bool,
    group_ids: list[int],
    user: User,
    db_session: Session,
) -> Skill:
    reject_reserved_skill_slug(filename)

    file_store = get_default_file_store()
    ingested = ingest_skill_bundle(read_bundle_file(bundle_file), filename, file_store)

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
        if group_ids:
            replace_skill_grants(skill.id, group_ids, db_session=db_session)
        db_session.commit()
    except Exception:
        delete_bundle_blob(file_store, ingested.bundle_file_id)
        raise

    push_skill_to_affected_sandboxes(skill, db_session)
    return skill


def create_personal_skill(
    *,
    bundle_file: BinaryIO,
    filename: str | None,
    user: User,
    db_session: Session,
) -> Skill:
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

    reject_reserved_skill_slug(filename)

    file_store = get_default_file_store()
    ingested = ingest_skill_bundle(read_bundle_file(bundle_file), filename, file_store)

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
    return skill


def patch_admin_custom_skill(
    *,
    skill_id: UUID,
    patch: SkillPatch,
    user: User,
    db_session: Session,
) -> Skill:
    skill = fetch_skill_for_edit(skill_id, user, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    ensure_custom_skill(skill)

    old_visibility = (skill.public_permission, skill.enabled)
    before_affected = affected_user_ids_for_skill(skill, db_session)

    updated = patch_skill(skill_id=skill_id, patch=patch, db_session=db_session)
    db_session.commit()

    visibility_changed = old_visibility != (updated.public_permission, updated.enabled)
    if visibility_changed:
        after_affected = affected_user_ids_for_skill(updated, db_session)
        push_skills_for_users(before_affected | after_affected, db_session)

    return updated


def patch_personal_skill(
    *,
    skill_id: UUID,
    enabled: bool,
    user: User,
    db_session: Session,
) -> Skill:
    skill = fetch_skill_by_id(skill_id, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    ensure_owned_personal_skill(skill, user, db_session)

    enabled_changed = skill.enabled != enabled
    before_affected = affected_user_ids_for_skill(skill, db_session)
    updated = patch_skill(
        skill_id=skill_id,
        patch=SkillPatch(enabled=enabled),
        db_session=db_session,
    )
    db_session.commit()

    if enabled_changed:
        after_affected = affected_user_ids_for_skill(updated, db_session)
        push_skills_for_users(before_affected | after_affected, db_session)
    return updated


def _replace_custom_skill_bundle(
    *,
    skill: Skill,
    bundle_file: BinaryIO,
    filename: str | None,
    db_session: Session,
) -> Skill:
    file_store = get_default_file_store()
    ingested = ingest_skill_bundle(
        read_bundle_file(bundle_file),
        filename,
        file_store,
        slug=skill.slug,
    )

    try:
        updated, old_file_id = replace_skill_bundle(
            skill_id=skill.id,
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
    return updated


def replace_admin_custom_skill_bundle(
    *,
    skill_id: UUID,
    bundle_file: BinaryIO,
    filename: str | None,
    user: User,
    db_session: Session,
) -> Skill:
    skill = fetch_skill_for_edit(skill_id, user, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    ensure_custom_skill(skill)

    return _replace_custom_skill_bundle(
        skill=skill,
        bundle_file=bundle_file,
        filename=filename,
        db_session=db_session,
    )


def replace_personal_skill_bundle(
    *,
    skill_id: UUID,
    bundle_file: BinaryIO,
    filename: str | None,
    user: User,
    db_session: Session,
) -> Skill:
    # fetch_skill_by_id bypasses the enabled filter on purpose: an
    # admin-disabled personal skill must stay mutable by its owner.
    skill = fetch_skill_by_id(skill_id, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    ensure_owned_personal_skill(skill, user, db_session)

    return _replace_custom_skill_bundle(
        skill=skill,
        bundle_file=bundle_file,
        filename=filename,
        db_session=db_session,
    )


def replace_admin_custom_skill_grants(
    *,
    skill_id: UUID,
    group_ids: list[int],
    user: User,
    db_session: Session,
) -> Skill:
    skill = fetch_skill_for_edit(skill_id, user, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    ensure_custom_skill(skill)

    before_affected = affected_user_ids_for_skill(skill, db_session)

    replace_skill_grants(skill_id, group_ids, db_session=db_session)
    db_session.commit()

    updated = fetch_skill_by_id(skill_id, db_session)
    if updated is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    after_affected = affected_user_ids_for_skill(updated, db_session)
    push_skills_for_users(before_affected | after_affected, db_session)
    return updated


def delete_admin_custom_skill(
    *,
    skill_id: UUID,
    user: User,
    db_session: Session,
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


def delete_personal_skill(
    *,
    skill_id: UUID,
    user: User,
    db_session: Session,
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
