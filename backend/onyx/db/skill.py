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

from sqlalchemy import and_
from sqlalchemy import delete
from sqlalchemy import or_
from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.enums import SandboxStatus
from onyx.db.external_app import is_user_authenticated_for_app
from onyx.db.models import ExternalApp
from onyx.db.models import ExternalAppUserCredential
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
from onyx.skills.built_in import BUILT_IN_SKILLS

SKILL_SLUG_UNIQUE_CONSTRAINT = "uq_skill_slug"


@dataclass(frozen=True, kw_only=True)
class SkillPatch:
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


def _exclude_unavailable_built_ins(
    stmt: Select[tuple[Skill]], db_session: Session
) -> Select[tuple[Skill]]:
    """Hide built-ins whose codified ``is_available(db)`` returns False.
    User reads use this; admin reads don't (admins see all rows)."""
    unavailable = [
        d.built_in_skill_id
        for d in BUILT_IN_SKILLS.values()
        if not d.is_available(db_session)
    ]
    if not unavailable:
        return stmt
    return stmt.where(
        or_(
            Skill.built_in_skill_id.is_(None),
            Skill.built_in_skill_id.notin_(unavailable),
        )
    )


def _external_app_skill_ids_subquery() -> Select[tuple[UUID]]:
    """Subquery of every skill id backed by an ``external_app`` row.

    Used with ``Skill.id.notin_(...)`` to keep external-app-backed skills
    out of the skills endpoint — they're managed through the
    external-apps API instead.
    """
    return select(ExternalApp.skill_id)


def _skill_ids_blocked_by_external_app_auth(
    user: User, db_session: Session
) -> list[UUID]:
    """Skill ids to withhold from *user*'s sandbox: external-app-backed
    skills the user has not authenticated for.

    Each external app is left-joined to this user's credential row; an app
    the user can't use yet (missing required credential keys) has its skill
    blocked. Apps that need no per-user credentials, or that the user has
    already configured, are not blocked.
    """
    rows = db_session.execute(
        select(ExternalApp, ExternalAppUserCredential).join(
            ExternalAppUserCredential,
            and_(
                ExternalAppUserCredential.external_app_id == ExternalApp.id,
                ExternalAppUserCredential.user_id == user.id,
            ),
            isouter=True,
        )
    ).all()
    return [
        app.skill_id
        for app, user_cred in rows
        if not is_user_authenticated_for_app(app, user_cred)
    ]


def list_skills_for_user(user: User, db_session: Session) -> Sequence[Skill]:
    """Skills the user sees in the skills endpoint.

    External-app-backed skills are excluded unconditionally — they're
    surfaced (and mutated) via the external-apps API only. Use
    ``list_skills_for_sandbox_injection`` to get the wider set the
    sandbox actually receives (which includes authenticated external
    apps).
    """
    stmt = (
        select(Skill)
        .where(Skill.enabled.is_(True))
        .where(Skill.id.notin_(_external_app_skill_ids_subquery()))
        .options(selectinload(Skill.author))
        .order_by(Skill.name)
    )
    stmt = _add_user_visibility_filter(stmt, user)
    stmt = _exclude_unavailable_built_ins(stmt, db_session)
    return list(db_session.scalars(stmt))


def fetch_skill_for_user(
    skill_id: UUID, user: User, db_session: Session
) -> Skill | None:
    """Skill the user can read via the skills endpoint. Returns ``None``
    for external-app-backed rows even when the id matches — the skills
    endpoint must not be a mutation seam for external apps."""
    stmt = (
        select(Skill)
        .where(Skill.id == skill_id)
        .where(Skill.enabled.is_(True))
        .where(Skill.id.notin_(_external_app_skill_ids_subquery()))
        .options(selectinload(Skill.author))
    )
    stmt = _add_user_visibility_filter(stmt, user)
    stmt = _exclude_unavailable_built_ins(stmt, db_session)
    return db_session.scalars(stmt).one_or_none()


def fetch_skill_for_user_by_slug(
    slug: str, user: User, db_session: Session
) -> Skill | None:
    """Slug variant of ``fetch_skill_for_user``. Same exclusion: never
    returns external-app-backed skills."""
    stmt = (
        select(Skill)
        .where(Skill.slug == slug)
        .where(Skill.enabled.is_(True))
        .where(Skill.id.notin_(_external_app_skill_ids_subquery()))
        .options(selectinload(Skill.author))
    )
    stmt = _add_user_visibility_filter(stmt, user)
    stmt = _exclude_unavailable_built_ins(stmt, db_session)
    return db_session.scalars(stmt).one_or_none()


def list_skills_for_sandbox_injection(
    user: User, db_session: Session
) -> Sequence[Skill]:
    """Skills delivered into *user*'s sandbox: every regular skill they
    can see, plus the external-app-backed skills they've authenticated
    for. Used by the sandbox skill-push path, NOT by the skills
    endpoint (which excludes external apps entirely)."""
    blocked = _skill_ids_blocked_by_external_app_auth(user, db_session)
    stmt = (
        select(Skill)
        .where(Skill.enabled.is_(True))
        .where(Skill.id.notin_(blocked))
        .options(selectinload(Skill.author))
        .order_by(Skill.name)
    )
    stmt = _add_user_visibility_filter(stmt, user)
    stmt = _exclude_unavailable_built_ins(stmt, db_session)
    return list(db_session.scalars(stmt))


def fetch_skill_for_admin(skill_id: UUID, db_session: Session) -> Skill | None:
    stmt = select(Skill).where(Skill.id == skill_id).options(selectinload(Skill.author))
    return db_session.scalars(stmt).one_or_none()


def list_skills_for_admin(db_session: Session) -> Sequence[Skill]:
    stmt = select(Skill).options(selectinload(Skill.author)).order_by(Skill.name)
    return list(db_session.scalars(stmt))


def create_skill__no_commit(
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


def create_built_in_skill_row__no_commit(
    *,
    built_in_skill_id: str,
    name: str,
    description: str,
    is_public: bool,
    enabled: bool,
    author_user_id: UUID | None = None,
    db_session: Session,
) -> Skill:
    """Create a built-in-style ``Skill`` row: ``built_in_skill_id`` set,
    ``slug == built_in_skill_id`` (the stable on-disk dir name), bundle fields
    NULL (per the XOR check constraint). Used for external-app providers, whose
    rows are created on demand rather than seeded.

    Because the slug is the (globally unique) built-in id, a tenant can hold at
    most one row per provider — a second attempt raises
    ``OnyxError(DUPLICATE_RESOURCE)``, which is the desired "connect Slack once"
    behaviour.
    """
    existing = db_session.scalars(
        select(Skill.id).where(Skill.slug == built_in_skill_id)
    ).first()
    if existing is not None:
        raise OnyxError(
            OnyxErrorCode.DUPLICATE_RESOURCE,
            f"A skill with slug '{built_in_skill_id}' already exists.",
        )

    skill = Skill(
        slug=built_in_skill_id,
        name=name,
        description=description,
        built_in_skill_id=built_in_skill_id,
        bundle_file_id=None,
        bundle_sha256=None,
        is_public=is_public,
        author_user_id=author_user_id,
        enabled=enabled,
    )
    db_session.add(skill)
    try:
        db_session.flush()
    except IntegrityError as e:
        if is_unique_violation(e, SKILL_SLUG_UNIQUE_CONSTRAINT):
            raise OnyxError(
                OnyxErrorCode.DUPLICATE_RESOURCE,
                f"A skill with slug '{built_in_skill_id}' already exists.",
            ) from e
        raise
    return skill


def replace_skill_bundle(
    *,
    skill_id: UUID,
    new_bundle_file_id: str,
    new_bundle_sha256: str,
    new_name: str,
    new_description: str,
    db_session: Session,
) -> tuple[Skill, str]:
    """Swap a custom skill's bundle blob and refresh its display metadata.

    Returns ``(skill, old_bundle_file_id)`` so the caller can delete the
    old blob from FileStore AFTER the transaction commits — never
    inline.

    Name and description come from the new bundle's SKILL.md frontmatter so
    the DB row stays in lockstep with what's actually pushed to sandboxes.

    Rejects built-in rows — they have no bundle.
    """
    skill = fetch_skill_for_admin(skill_id, db_session)
    if skill is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"Skill {skill_id} not found.",
        )
    if skill.built_in_skill_id is not None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Skill '{skill.slug}' is a built-in and has no bundle.",
        )

    # Custom rows always have a bundle (XOR check constraint), but guard
    # explicitly rather than assert so a corrupt row fails loud, not silent.
    if skill.bundle_file_id is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Skill '{skill.slug}' has no bundle to replace.",
        )

    old_bundle_file_id = skill.bundle_file_id
    skill.bundle_file_id = new_bundle_file_id
    skill.bundle_sha256 = new_bundle_sha256
    skill.name = new_name
    skill.description = new_description
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

    for field in ("is_public", "enabled"):
        value = getattr(patch, field)
        if not isinstance(value, UnsetType):
            setattr(skill, field, value)

    db_session.flush()
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
