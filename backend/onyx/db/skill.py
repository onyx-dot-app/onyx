"""DB operations for custom (admin-uploaded) skills.

Access model:
- Admin reads: see every row. Disabled skills stay visible so admins can
  re-enable them.
- User reads: filter `enabled = True`, plus `is_public` OR the user is in a
  group that has been granted access.

Delete is a hard delete — `delete_skill` removes the row and returns its
`bundle_file_id` so the caller can drop the blob from the file store
immediately (skills sync via S3-backed bundles, so blob retention isn't
needed).

These helpers never commit — callers control the transaction boundary so a
multi-step admin flow (e.g. create row + replace grants) can roll back atomically.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy import or_
from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox
from onyx.db.models import Skill
from onyx.db.models import Skill__UserGroup
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.utils import is_fk_violation
from onyx.db.utils import is_unique_violation
from onyx.db.utils import UNSET
from onyx.db.utils import UnsetType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

SKILL_SLUG_UNIQUE_CONSTRAINT = "uq_skill_slug"


@dataclass(frozen=True, kw_only=True)
class SkillPatch:
    slug: str | UnsetType = UNSET
    name: str | UnsetType = UNSET
    description: str | UnsetType = UNSET
    is_public: bool | UnsetType = UNSET
    enabled: bool | UnsetType = UNSET


def _add_user_visibility_filter(
    stmt: Select[tuple[Skill]], user: User
) -> Select[tuple[Skill]]:
    """Restrict a `select(Skill)` to rows the given user can see.

    Admins bypass the filter; everyone else goes through the
    is_public-or-group-grant path.
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
    stmt = select(Skill).where(Skill.enabled.is_(True)).order_by(Skill.name)
    stmt = _add_user_visibility_filter(stmt, user)
    return list(db_session.scalars(stmt))


def fetch_skill_for_user(
    skill_id: UUID, user: User, db_session: Session
) -> Skill | None:
    stmt = select(Skill).where(Skill.id == skill_id).where(Skill.enabled.is_(True))
    stmt = _add_user_visibility_filter(stmt, user)
    return db_session.scalars(stmt).one_or_none()


def fetch_skill_for_admin(skill_id: UUID, db_session: Session) -> Skill | None:
    stmt = select(Skill).where(Skill.id == skill_id)
    return db_session.scalars(stmt).one_or_none()


def list_skills_for_admin(db_session: Session) -> Sequence[Skill]:
    stmt = select(Skill).order_by(Skill.name)
    return list(db_session.scalars(stmt))


def create_skill(
    *,
    slug: str,
    name: str,
    description: str,
    bundle_file_id: str,
    bundle_sha256: str,
    is_public: bool,
    author_user_id: UUID | None,
    db_session: Session,
) -> Skill:
    existing = db_session.scalars(select(Skill.id).where(Skill.slug == slug)).first()
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
        is_public=is_public,
        author_user_id=author_user_id,
        enabled=True,
    )
    db_session.add(skill)
    try:
        db_session.flush()
    except IntegrityError as e:
        if is_unique_violation(e, SKILL_SLUG_UNIQUE_CONSTRAINT):
            raise OnyxError(
                OnyxErrorCode.DUPLICATE_RESOURCE,
                f"A skill with slug '{slug}' already exists.",
            ) from e
        raise
    return skill


def replace_skill_bundle(
    *,
    skill_id: UUID,
    new_bundle_file_id: str,
    new_bundle_sha256: str,
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
    db_session.flush()
    return skill, old_bundle_file_id


def patch_skill(
    *,
    skill_id: UUID,
    patch: SkillPatch,
    db_session: Session,
) -> Skill:
    skill = fetch_skill_for_admin(skill_id, db_session)
    if skill is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"Skill {skill_id} not found.",
        )

    # Apply simple field updates
    for field in ("name", "description", "is_public", "enabled"):
        value = getattr(patch, field)
        if not isinstance(value, UnsetType):
            setattr(skill, field, value)

    # Slug requires a uniqueness pre-check
    slug_changed = False
    if not isinstance(patch.slug, UnsetType):
        new_slug: str = patch.slug
        if new_slug != skill.slug:
            slug_changed = True
            exists = db_session.scalars(
                select(Skill.id)
                .where(Skill.slug == new_slug)
                .where(Skill.id != skill_id)
            ).first()
            if exists is not None:
                raise OnyxError(
                    OnyxErrorCode.DUPLICATE_RESOURCE,
                    f"A skill with slug '{new_slug}' already exists.",
                )
            skill.slug = new_slug

    try:
        db_session.flush()
    except IntegrityError as e:
        if slug_changed and is_unique_violation(e, SKILL_SLUG_UNIQUE_CONSTRAINT):
            raise OnyxError(
                OnyxErrorCode.DUPLICATE_RESOURCE,
                f"A skill with slug '{patch.slug}' already exists.",
            ) from e
        raise
    return skill


def replace_skill_grants(
    skill_id: UUID, group_ids: Sequence[int], db_session: Session
) -> None:
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
    try:
        db_session.flush()
    except IntegrityError as e:
        if is_fk_violation(e):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "One or more group IDs do not exist.",
            ) from e
        raise


def delete_skill(skill_id: UUID, db_session: Session) -> str | None:
    """Hard-delete a skill and return its `bundle_file_id` for caller cleanup."""
    skill = fetch_skill_for_admin(skill_id, db_session)
    if skill is None:
        return None
    bundle_file_id = skill.bundle_file_id
    db_session.delete(skill)
    db_session.flush()
    return bundle_file_id


def affected_user_ids_for_skill(skill: Skill, db_session: Session) -> set[UUID]:
    """Return user IDs with an active sandbox who should have this skill.

    Does not filter by ``enabled`` — callers use this for both enable and
    disable transitions (the pushed fileset handles the actual filtering).
    """
    if skill.is_public:
        stmt = select(Sandbox.user_id).where(Sandbox.status == SandboxStatus.RUNNING)
        return set(db_session.scalars(stmt))

    stmt = (
        select(Sandbox.user_id)
        .join(
            User__UserGroup,
            User__UserGroup.user_id == Sandbox.user_id,
        )
        .join(
            Skill__UserGroup,
            Skill__UserGroup.user_group_id == User__UserGroup.user_group_id,
        )
        .where(Skill__UserGroup.skill_id == skill.id)
        .where(Sandbox.status == SandboxStatus.RUNNING)
    )
    return set(db_session.scalars(stmt))


def get_group_ids_for_skill(skill_id: UUID, db_session: Session) -> list[int]:
    stmt = select(Skill__UserGroup.user_group_id).where(
        Skill__UserGroup.skill_id == skill_id
    )
    return list(db_session.scalars(stmt))
