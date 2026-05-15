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
from uuid import UUID

from sqlalchemy import delete
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
from onyx.db.utils import is_unique_violation
from onyx.db.utils import UNSET
from onyx.db.utils import UnsetType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.registry import CustomSkill

# Name of the unique constraint on `skill.slug` (declared on the model and
# created by the Skills V1 migration). Used to translate the specific
# collision into `DUPLICATE_RESOURCE`.
SKILL_SLUG_UNIQUE_CONSTRAINT = "uq_skill_slug"


def _custom_skill_from_model(skill: Skill) -> CustomSkill:
    return CustomSkill(
        id=skill.id,
        slug=skill.slug,
        name=skill.name,
        description=skill.description,
        bundle_file_id=skill.bundle_file_id,
        bundle_sha256=skill.bundle_sha256,
        is_public=skill.is_public,
        enabled=skill.enabled,
    )


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


def list_skills_for_user(user: User, db_session: Session) -> Sequence[CustomSkill]:
    """Skills the user can use in a session.

    Filtered to `enabled = True`: disabled skills never reach the materializer.
    """
    stmt = select(Skill).where(Skill.enabled.is_(True)).order_by(Skill.name)
    stmt = _add_user_visibility_filter(stmt, user)
    return [_custom_skill_from_model(skill) for skill in db_session.scalars(stmt)]


def fetch_skill_for_user(
    skill_id: UUID, user: User, db_session: Session
) -> CustomSkill | None:
    """Single-skill lookup with the same filter as `list_skills_for_user`.

    Returns None when the skill does not exist, is disabled, or the user has
    no grant — callers translate to 404 as needed.
    """
    stmt = select(Skill).where(Skill.id == skill_id).where(Skill.enabled.is_(True))
    stmt = _add_user_visibility_filter(stmt, user)
    skill = db_session.scalars(stmt).one_or_none()
    return _custom_skill_from_model(skill) if skill is not None else None


def _fetch_skill_model_for_admin(skill_id: UUID, db_session: Session) -> Skill | None:
    """Admin lookup (no `enabled` filter — disabled skills are still visible)."""
    stmt = select(Skill).where(Skill.id == skill_id)
    return db_session.scalars(stmt).one_or_none()


def fetch_skill_for_admin(skill_id: UUID, db_session: Session) -> CustomSkill | None:
    """Admin lookup (no `enabled` filter — disabled skills are still visible)."""
    skill = _fetch_skill_model_for_admin(skill_id, db_session)
    return _custom_skill_from_model(skill) if skill is not None else None


def list_skills_for_admin(db_session: Session) -> Sequence[CustomSkill]:
    """All skills, for the admin UI.

    Disabled skills are included so the admin can re-enable them.
    """
    stmt = select(Skill).order_by(Skill.name)
    return [_custom_skill_from_model(skill) for skill in db_session.scalars(stmt)]


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
) -> CustomSkill:
    """Insert a new Skill row.

    Slug collisions are caught two ways: a pre-check for the fast happy path,
    and an IntegrityError handler on flush that translates the `uq_skill_slug`
    constraint violation into `OnyxError(DUPLICATE_RESOURCE)` for the
    concurrent-writer race. Both raise the same structured error so callers
    never see a raw IntegrityError.
    """
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
    return _custom_skill_from_model(skill)


def replace_skill_bundle(
    *,
    skill_id: UUID,
    new_bundle_file_id: str,
    new_bundle_sha256: str,
    db_session: Session,
) -> tuple[CustomSkill, str]:
    """Swap a skill's bundle blob.

    Returns `(skill, old_bundle_file_id)` so the caller can delete the old
    blob from FileStore AFTER the transaction commits — never inline.
    """
    skill = _fetch_skill_model_for_admin(skill_id, db_session)
    if skill is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"Skill {skill_id} not found.",
        )

    old_bundle_file_id = skill.bundle_file_id
    skill.bundle_file_id = new_bundle_file_id
    skill.bundle_sha256 = new_bundle_sha256
    db_session.flush()
    return _custom_skill_from_model(skill), old_bundle_file_id


def patch_skill(
    *,
    skill_id: UUID,
    slug: str | UnsetType = UNSET,
    name: str | UnsetType = UNSET,
    description: str | UnsetType = UNSET,
    is_public: bool | UnsetType = UNSET,
    enabled: bool | UnsetType = UNSET,
    db_session: Session,
) -> CustomSkill:
    """Partial update of admin-controlled metadata.

    `UNSET` distinguishes "leave alone" from "set to None/falsy". Slug
    uniqueness is re-checked when the slug changes (the `uq_skill_slug`
    constraint is the DB backstop; this raises `DUPLICATE_RESOURCE` first
    for a clean structured error).
    """
    skill = _fetch_skill_model_for_admin(skill_id, db_session)
    if skill is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"Skill {skill_id} not found.",
        )

    slug_changed = not isinstance(slug, UnsetType) and slug != skill.slug
    if slug_changed:
        assert not isinstance(slug, UnsetType)
        clashing = db_session.scalars(
            select(Skill.id).where(Skill.slug == slug).where(Skill.id != skill_id)
        ).first()
        if clashing is not None:
            raise OnyxError(
                OnyxErrorCode.DUPLICATE_RESOURCE,
                f"A skill with slug '{slug}' already exists.",
            )
        skill.slug = slug

    if not isinstance(name, UnsetType):
        skill.name = name
    if not isinstance(description, UnsetType):
        skill.description = description
    if not isinstance(is_public, UnsetType):
        skill.is_public = is_public
    if not isinstance(enabled, UnsetType):
        skill.enabled = enabled

    try:
        db_session.flush()
    except IntegrityError as e:
        if slug_changed and is_unique_violation(e, SKILL_SLUG_UNIQUE_CONSTRAINT):
            raise OnyxError(
                OnyxErrorCode.DUPLICATE_RESOURCE,
                f"A skill with slug '{slug}' already exists.",
            ) from e
        raise
    return _custom_skill_from_model(skill)


def replace_skill_grants(
    skill_id: UUID, group_ids: Sequence[int], db_session: Session
) -> None:
    """Replace all group grants for a skill in a single transaction.

    Dedups the input. Does not commit — the caller owns the transaction.
    """
    if _fetch_skill_model_for_admin(skill_id, db_session) is None:
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


def delete_skill(skill_id: UUID, db_session: Session) -> str | None:
    """Hard-delete a skill and return its `bundle_file_id` for caller cleanup.

    Returns `None` if the skill did not exist (idempotent). The
    `skill__user_group` rows cascade delete via the FK. The caller is
    responsible for removing the bundle blob from the file store AFTER
    the transaction commits; running sandbox pods keep their materialized
    copy until the next bundle-sync cycle.
    """
    skill = _fetch_skill_model_for_admin(skill_id, db_session)
    if skill is None:
        return None
    # TODO: delete the bundle blob from S3 (file store) once the API caller
    # wires this up — currently returned for the caller to handle.
    bundle_file_id = skill.bundle_file_id
    db_session.delete(skill)
    db_session.flush()
    return bundle_file_id
