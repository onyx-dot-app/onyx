from typing import Final
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.enums import AccountType
from onyx.db.enums import SkillAccessLevel
from onyx.db.enums import SkillSharePermission
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.db.skill import affected_user_ids_for_skill
from onyx.db.skill import create_skill__no_commit
from onyx.db.skill import delete_skill
from onyx.db.skill import fetch_skill
from onyx.db.skill import fetch_skill_by_id_for_system
from onyx.db.skill import replace_skill_bundle
from onyx.db.skill import replace_skill_shares
from onyx.db.skill import SkillAccessPolicy
from onyx.db.skill import transfer_skill_ownership
from onyx.db.skill import update_skill_fields
from onyx.db.users import fetch_user_by_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.skill.models import SkillPatchRequest
from onyx.server.features.skill.models import SkillShareRequest
from onyx.server.features.skill.models import TransferSkillOwnershipRequest
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.built_in import EXTERNAL_APP_BUILT_IN_SKILL_IDS
from onyx.skills.bundle import compute_bundle_sha256
from onyx.skills.bundle import read_custom_bundle_instructions
from onyx.skills.bundle import rewrite_custom_bundle_skill_md
from onyx.skills.bundle import slug_from_filename
from onyx.skills.content import read_custom_skill_bundle_bytes
from onyx.skills.ingest import delete_bundle_blob
from onyx.skills.ingest import ingest_skill_bundle
from onyx.skills.ingest import save_skill_bundle_bytes
from onyx.skills.push import push_skill_to_affected_sandboxes
from onyx.skills.push import push_skills_for_users

_RESERVED_SKILL_SLUGS: Final[frozenset[str]] = frozenset(BUILT_IN_SKILLS) | frozenset(
    EXTERNAL_APP_BUILT_IN_SKILL_IDS.values()
)


def user_permission_for_skill(
    skill: Skill,
    user: User,
    user_group_ids: set[int],
    curated_user_group_ids: set[int] | None = None,
) -> SkillAccessLevel | None:
    if skill.built_in_skill_id is not None:
        return SkillAccessLevel.VIEWER

    if skill.author_user_id == user.id:
        return SkillAccessLevel.OWNER

    if user.role == UserRole.ADMIN:
        return SkillAccessLevel.EDITOR

    direct_permissions = {
        share.permission for share in skill.user_shares if share.user_id == user.id
    }
    group_permissions = {
        share.permission
        for share in skill.group_shares
        if share.user_group_id in user_group_ids
    }
    share_permissions = direct_permissions | group_permissions

    is_org_shared = skill.public_permission is not None
    is_shared_with_user = bool(share_permissions)
    group_share_ids = {share.user_group_id for share in skill.group_shares}
    curator_managed_group_ids = set[int]()
    if user.role == UserRole.GLOBAL_CURATOR:
        curator_managed_group_ids = user_group_ids
    elif user.role == UserRole.CURATOR:
        curator_managed_group_ids = curated_user_group_ids or set()
    is_curator_managed = (
        bool(group_share_ids)
        and bool(curator_managed_group_ids)
        and group_share_ids <= curator_managed_group_ids
    )
    has_explicit_edit = (
        SkillSharePermission.EDITOR in share_permissions
        or is_org_shared
        and skill.public_permission == SkillSharePermission.EDITOR
    )

    if has_explicit_edit:
        return SkillAccessLevel.EDITOR

    if is_curator_managed:
        return SkillAccessLevel.EDITOR

    if is_org_shared or is_shared_with_user:
        return SkillAccessLevel.VIEWER

    return None


def _refetch_skill_or_404(skill_id: UUID, db_session: Session) -> Skill:
    skill = fetch_skill_by_id_for_system(skill_id, db_session)
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    return skill


def _ensure_can_edit_org_visibility(skill: Skill, user: User) -> None:
    if skill.author_user_id == user.id:
        return
    if user.role == UserRole.ADMIN:
        return
    raise OnyxError(
        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
        "You do not have permission to change organization-wide skill access.",
    )


def get_editable_custom_skill(
    skill_id: UUID,
    user: User,
    db_session: Session,
) -> Skill:
    skill = fetch_skill(
        skill_id,
        policy=SkillAccessPolicy.EDIT,
        user=user,
        db_session=db_session,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    return skill


def create_custom_skill_for_user(
    *,
    bundle_bytes: bytes,
    filename: str | None,
    user: User,
    db_session: Session,
) -> Skill:
    slug = slug_from_filename(filename)
    if slug in _RESERVED_SKILL_SLUGS:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, f"slug '{slug}' is reserved")

    file_store = get_default_file_store()
    ingested = ingest_skill_bundle(bundle_bytes, filename, file_store, slug=slug)

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


def patch_custom_skill_for_user(
    *,
    skill_id: UUID,
    patch: SkillPatchRequest,
    user: User,
    db_session: Session,
) -> Skill:
    skill = get_editable_custom_skill(skill_id, user, db_session)
    if {"is_public", "public_permission"} & patch.model_fields_set:
        _ensure_can_edit_org_visibility(skill, user)

    if not (patch.has_details_update or patch.has_db_field_update):
        return skill

    old_visibility = (skill.public_permission, skill.enabled)
    before_affected = affected_user_ids_for_skill(skill, db_session)

    file_store = get_default_file_store() if patch.has_details_update else None
    new_bundle_file_id: str | None = None
    old_bundle_file_id: str | None = None

    try:
        if file_store is not None:
            old_bundle_bytes = read_custom_skill_bundle_bytes(skill, file_store)
            name = patch.name if patch.name is not None else skill.name
            description = (
                patch.description
                if patch.description is not None
                else skill.description
            )
            instructions_markdown = patch.instructions_markdown
            if instructions_markdown is None:
                instructions_markdown = read_custom_bundle_instructions(
                    old_bundle_bytes
                )
            new_bundle_bytes = rewrite_custom_bundle_skill_md(
                old_bundle_bytes,
                slug=skill.slug,
                name=name,
                description=description,
                instructions_markdown=instructions_markdown,
            )
            new_bundle_file_id = save_skill_bundle_bytes(
                new_bundle_bytes,
                display_name=f"{skill.slug}.zip",
                file_store=file_store,
            )
            old_bundle_file_id = replace_skill_bundle(
                skill=skill,
                new_bundle_file_id=new_bundle_file_id,
                new_bundle_sha256=compute_bundle_sha256(new_bundle_bytes),
                new_name=name,
                new_description=description,
                db_session=db_session,
            )

        if patch.has_db_field_update:
            is_public = (
                patch.is_public if "is_public" in patch.model_fields_set else None
            )
            public_permission = (
                patch.public_permission
                if "public_permission" in patch.model_fields_set
                else None
            )
            enabled = patch.enabled if "enabled" in patch.model_fields_set else None
            update_skill_fields(
                skill=skill,
                is_public=is_public,
                public_permission=public_permission,
                enabled=enabled,
                db_session=db_session,
            )

        db_session.commit()
    except Exception:
        if file_store is not None and new_bundle_file_id is not None:
            delete_bundle_blob(file_store, new_bundle_file_id)
        raise

    updated = _refetch_skill_or_404(skill_id, db_session)
    visibility_changed = old_visibility != (
        updated.public_permission,
        updated.enabled,
    )
    if patch.has_details_update or visibility_changed:
        after_affected = affected_user_ids_for_skill(updated, db_session)
        push_skills_for_users(before_affected | after_affected, db_session)

    if file_store is not None and old_bundle_file_id is not None:
        delete_bundle_blob(file_store, old_bundle_file_id)
    return updated


def update_custom_skill_shares_for_user(
    *,
    skill_id: UUID,
    share: SkillShareRequest,
    user: User,
    db_session: Session,
) -> Skill:
    skill = get_editable_custom_skill(skill_id, user, db_session)
    if (
        share.user_shares is None
        and share.group_shares is None
        and share.is_public is None
        and share.public_permission is None
    ):
        return skill

    touches_org_visibility = (
        share.is_public is not None or share.public_permission is not None
    )
    if touches_org_visibility:
        _ensure_can_edit_org_visibility(skill, user)

    before_affected = affected_user_ids_for_skill(skill, db_session)
    if touches_org_visibility:
        update_skill_fields(
            skill=skill,
            is_public=share.is_public,
            public_permission=share.public_permission,
            db_session=db_session,
        )

    user_shares: dict[UUID, SkillSharePermission] | None = None
    if share.user_shares is not None:
        user_shares = {
            user_share.user_id: user_share.permission
            for user_share in share.user_shares
            if user_share.user_id != skill.author_user_id
        }

    group_shares: dict[int, SkillSharePermission] | None = None
    if share.group_shares is not None:
        group_shares = {
            group_share.group_id: group_share.permission
            for group_share in share.group_shares
        }

    replace_skill_shares(
        skill=skill,
        user_shares=user_shares,
        group_shares=group_shares,
        db_session=db_session,
    )

    db_session.commit()
    updated = _refetch_skill_or_404(skill.id, db_session)
    after_affected = affected_user_ids_for_skill(updated, db_session)
    push_skills_for_users(before_affected | after_affected, db_session)
    return updated


def transfer_custom_skill_ownership_for_user(
    *,
    skill_id: UUID,
    transfer: TransferSkillOwnershipRequest,
    user: User,
    db_session: Session,
) -> Skill:
    skill = fetch_skill(
        skill_id,
        policy=SkillAccessPolicy.VIEW,
        user=user,
        db_session=db_session,
    )
    if skill is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    if skill.built_in_skill_id is not None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Skill '{skill.slug}' is a built-in and cannot change ownership.",
        )

    ownership_vacant = (
        skill.author_user_id is None
        or skill.author is None
        or not skill.author.is_active
    )
    if skill.author_user_id != user.id and not (
        user.role == UserRole.ADMIN and ownership_vacant
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Only the owner can transfer ownership of this skill.",
        )

    target = fetch_user_by_id(db_session, transfer.new_owner_user_id)
    if target is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "New owner not found.")
    if not target.is_active:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Ownership can only be transferred to an active user.",
        )
    if target.role in [UserRole.SLACK_USER, UserRole.EXT_PERM_USER, UserRole.LIMITED]:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Ownership cannot be transferred to this account type.",
        )
    if target.account_type is not None and target.account_type != AccountType.STANDARD:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Ownership cannot be transferred to bots or service accounts.",
        )
    if target.id == skill.author_user_id:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "This user already owns the skill.",
        )

    before_affected = affected_user_ids_for_skill(skill, db_session)
    transfer_skill_ownership(
        skill=skill,
        new_owner_user_id=target.id,
        db_session=db_session,
    )

    db_session.commit()
    updated = _refetch_skill_or_404(skill.id, db_session)
    after_affected = affected_user_ids_for_skill(updated, db_session)
    push_skills_for_users(before_affected | after_affected, db_session)
    return updated


def replace_custom_skill_bundle_for_user(
    *,
    skill_id: UUID,
    bundle_bytes: bytes,
    filename: str | None,
    user: User,
    db_session: Session,
) -> Skill:
    skill = get_editable_custom_skill(skill_id, user, db_session)

    file_store = get_default_file_store()
    ingested = ingest_skill_bundle(
        bundle_bytes,
        filename,
        file_store,
        slug=skill.slug,
    )

    try:
        old_file_id = replace_skill_bundle(
            skill=skill,
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

    updated = _refetch_skill_or_404(skill_id, db_session)
    push_skill_to_affected_sandboxes(updated, db_session)
    delete_bundle_blob(file_store, old_file_id)
    return updated


def delete_custom_skill_for_user(
    *,
    skill_id: UUID,
    user: User,
    db_session: Session,
) -> None:
    skill = get_editable_custom_skill(skill_id, user, db_session)

    affected = affected_user_ids_for_skill(skill, db_session)
    old_file_id = delete_skill(skill, db_session)
    db_session.commit()

    push_skills_for_users(affected, db_session)
    if old_file_id is not None:
        delete_bundle_blob(get_default_file_store(), old_file_id)
