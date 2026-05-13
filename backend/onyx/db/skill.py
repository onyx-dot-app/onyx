"""DB operations for custom (admin-uploaded) skills.

Access model:
- Admin reads: filter `deleted_at IS NULL` only. Disabled skills stay visible
  so admins can re-enable them.
- User reads: filter `enabled = True AND deleted_at IS NULL`, plus `is_public`
  OR the user is in a group that has been granted access.

These helpers never commit — callers control the transaction boundary so a
multi-step admin flow (e.g. create row + replace grants) can roll back atomically.
"""

from collections.abc import Sequence
from typing import Any
from typing import Final
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.models import Skill
from onyx.db.models import Skill__UserGroup
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


class _UnsetType:
    """Sentinel distinguishing 'not provided' from None/falsy in patch helpers.

    Typed as a dedicated class (instead of `Final[Any]`) so unions like
    `str | _UnsetType` retain their real type at the call site — `str | Any`
    collapses to `Any` and silently disables type checking on the parameter.
    """


_UNSET: Final[_UnsetType] = _UnsetType()


def _add_user_visibility_filter(
    stmt: Select[tuple[Skill]], user: User
) -> Select[tuple[Skill]]:
    """Restrict a `select(Skill)` to rows the given user can see.

    Mirrors `onyx.db.persona._add_user_filters` minus the direct user-grant
    branch (no `Skill__User` table in V1). Admins bypass the filter; everyone
    else — including `GLOBAL_CURATOR` and `CURATOR` — goes through the
    is_public-or-group-grant path. The curator-specific elevated access in
    persona exists to gate *editability* of curator-owned personas; skills
    have no editability dimension at the user-read layer in V1 (only admins
    mutate skills), so global-curators are intentionally treated the same as
    regular users for visibility.
    """
    if user.role == UserRole.ADMIN:
        return stmt

    group_grant_exists = (
        select(Skill__UserGroup.skill_id)
        .join(
            User__UserGroup,
            User__UserGroup.user_group_id == Skill__UserGroup.user_group_id,
        )
        .where(Skill__UserGroup.skill_id == Skill.id)
        .where(User__UserGroup.user_id == user.id)
        .exists()
    )

    return stmt.where(or_(Skill.is_public.is_(True), group_grant_exists))


def list_skills_for_user(user: User, db_session: Session) -> Sequence[Skill]:
    """Skills the user can use in a session.

    Filtered to `enabled = True AND deleted_at IS NULL`: disabled or soft-deleted
    skills never reach the materializer.
    """
    stmt = (
        select(Skill)
        .where(Skill.enabled.is_(True))
        .where(Skill.deleted_at.is_(None))
        .order_by(Skill.name)
    )
    stmt = _add_user_visibility_filter(stmt, user)
    return db_session.scalars(stmt).all()


def fetch_skill_for_user(
    skill_id: UUID, user: User, db_session: Session
) -> Skill | None:
    """Single-skill lookup with the same filter as `list_skills_for_user`.

    Returns None when the skill does not exist, is disabled, soft-deleted, or
    the user has no grant — callers translate to 404 as needed.
    """
    stmt = (
        select(Skill)
        .where(Skill.id == skill_id)
        .where(Skill.enabled.is_(True))
        .where(Skill.deleted_at.is_(None))
    )
    stmt = _add_user_visibility_filter(stmt, user)
    return db_session.scalars(stmt).one_or_none()


def fetch_skill_for_admin(skill_id: UUID, db_session: Session) -> Skill | None:
    """Admin lookup: `deleted_at IS NULL` only (no `enabled` filter)."""
    stmt = select(Skill).where(Skill.id == skill_id).where(Skill.deleted_at.is_(None))
    return db_session.scalars(stmt).one_or_none()


def list_skills_for_admin(db_session: Session) -> Sequence[Skill]:
    """All non-soft-deleted skills, for the admin UI.

    Disabled skills are included so the admin can re-enable them; soft-deleted
    rows are hidden by default (engineer-only undelete bypasses this helper).
    """
    stmt = select(Skill).where(Skill.deleted_at.is_(None)).order_by(Skill.name)
    return db_session.scalars(stmt).all()


def create_skill(
    *,
    slug: str,
    name: str,
    description: str,
    bundle_file_id: str,
    bundle_sha256: str,
    manifest_metadata: dict[str, Any],
    is_public: bool,
    author_user_id: UUID | None,
    db_session: Session,
) -> Skill:
    """Insert a new Skill row.

    Slug collisions are caught two ways: a pre-check for the fast happy path,
    and a SAVEPOINT-wrapped flush that translates the partial unique index's
    IntegrityError into `OnyxError(DUPLICATE_RESOURCE)` for the concurrent-
    writer race. Both raise the same structured error so callers never see
    a raw IntegrityError.
    """
    existing = db_session.scalars(
        select(Skill.id).where(Skill.slug == slug).where(Skill.deleted_at.is_(None))
    ).first()
    if existing is not None:
        raise OnyxError(
            OnyxErrorCode.DUPLICATE_RESOURCE,
            f"A skill with slug '{slug}' already exists.",
        )

    skill = Skill(
        slug=slug,
        name=name,
        description=description,
        bundle_file_id=bundle_file_id,
        bundle_sha256=bundle_sha256,
        manifest_metadata=manifest_metadata,
        is_public=is_public,
        author_user_id=author_user_id,
        enabled=True,
    )
    try:
        with db_session.begin_nested():
            db_session.add(skill)
            db_session.flush()
    except IntegrityError as e:
        raise OnyxError(
            OnyxErrorCode.DUPLICATE_RESOURCE,
            f"A skill with slug '{slug}' already exists.",
        ) from e
    return skill


def replace_skill_bundle(
    *,
    skill_id: UUID,
    new_bundle_file_id: str,
    new_bundle_sha256: str,
    new_manifest_metadata: dict[str, Any],
    db_session: Session,
) -> tuple[Skill, str]:
    """Swap a skill's bundle blob.

    Returns `(skill, old_bundle_file_id)` so the caller can delete the old
    blob from FileStore AFTER the transaction commits — never inline.
    """
    skill = fetch_skill_for_admin(skill_id, db_session)
    if skill is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"Skill {skill_id} not found.",
        )

    old_bundle_file_id = skill.bundle_file_id
    skill.bundle_file_id = new_bundle_file_id
    skill.bundle_sha256 = new_bundle_sha256
    skill.manifest_metadata = new_manifest_metadata
    db_session.flush()
    return skill, old_bundle_file_id


def patch_skill(
    *,
    skill_id: UUID,
    slug: str | _UnsetType = _UNSET,
    name: str | _UnsetType = _UNSET,
    description: str | _UnsetType = _UNSET,
    is_public: bool | _UnsetType = _UNSET,
    enabled: bool | _UnsetType = _UNSET,
    db_session: Session,
) -> Skill:
    """Partial update of admin-controlled metadata.

    `_UNSET` distinguishes "leave alone" from "set to None/falsy". Slug
    uniqueness is re-checked when the slug changes (the partial unique index
    is the DB backstop; this raises `DUPLICATE_RESOURCE` first for a clean
    structured error).
    """
    skill = fetch_skill_for_admin(skill_id, db_session)
    if skill is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"Skill {skill_id} not found.",
        )

    slug_changed = not isinstance(slug, _UnsetType) and slug != skill.slug
    if slug_changed:
        assert not isinstance(slug, _UnsetType)
        clashing = db_session.scalars(
            select(Skill.id)
            .where(Skill.slug == slug)
            .where(Skill.deleted_at.is_(None))
            .where(Skill.id != skill_id)
        ).first()
        if clashing is not None:
            raise OnyxError(
                OnyxErrorCode.DUPLICATE_RESOURCE,
                f"A skill with slug '{slug}' already exists.",
            )
        skill.slug = slug

    if not isinstance(name, _UnsetType):
        skill.name = name
    if not isinstance(description, _UnsetType):
        skill.description = description
    if not isinstance(is_public, _UnsetType):
        skill.is_public = is_public
    if not isinstance(enabled, _UnsetType):
        skill.enabled = enabled

    try:
        with db_session.begin_nested():
            db_session.flush()
    except IntegrityError as e:
        if slug_changed:
            raise OnyxError(
                OnyxErrorCode.DUPLICATE_RESOURCE,
                f"A skill with slug '{slug}' already exists.",
            ) from e
        raise
    return skill


def replace_skill_grants(
    skill_id: UUID, group_ids: Sequence[int], db_session: Session
) -> None:
    """Replace all group grants for a skill in a single transaction.

    Dedups the input. Does not commit — the caller owns the transaction.
    """
    if fetch_skill_for_admin(skill_id, db_session) is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"Skill {skill_id} not found.",
        )
    db_session.execute(
        delete(Skill__UserGroup).where(Skill__UserGroup.skill_id == skill_id)
    )
    seen: set[int] = set()
    for group_id in group_ids:
        if group_id in seen:
            continue
        seen.add(group_id)
        db_session.add(Skill__UserGroup(skill_id=skill_id, user_group_id=group_id))
    db_session.flush()


def delete_skill(skill_id: UUID, db_session: Session) -> None:
    """Soft-delete by stamping `deleted_at = now()`.

    The bundle blob is NOT removed inline; the weekly sweep (§16) deletes it
    after the soft-delete ages past the retention window, then hard-deletes
    the row. Running sessions continue to use the on-pod copy.

    Idempotent: re-deleting an already-deleted skill is a no-op.
    """
    skill = fetch_skill_for_admin(skill_id, db_session)
    if skill is None:
        return
    skill.deleted_at = func.now()
    db_session.flush()
