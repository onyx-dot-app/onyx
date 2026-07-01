"""DB operations for skill rows.

Access model:
- `VIEW` is the skills UI/read API policy. It excludes external-app-backed rows,
  applies user visibility, and lets admins view all non-external-app rows.
- `EDIT` is the skill mutation policy. It excludes external-app-backed
  and built-in rows, and only returns rows the user can modify.
- `USE` is the runtime/sandbox policy. It applies user visibility without an
  admin bypass, requires enabled rows, includes available external-app-backed
  rows, and hides unavailable built-ins.

Delete is a hard delete — `delete_skill` removes the row and returns its
`bundle_file_id` so the caller can drop the blob from the file store
immediately (skills sync via S3-backed bundles, so blob retention isn't
needed).

These helpers never commit — callers control the transaction boundary so a
multi-step admin flow (e.g. create row + replace grants) can roll back atomically.
"""

import hashlib
import struct
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy import ColumnElement
from sqlalchemy import delete
from sqlalchemy import exists
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.enums import SandboxStatus
from onyx.db.enums import SkillSharePermission
from onyx.db.external_app import is_user_authenticated_for_app
from onyx.db.models import ExternalApp
from onyx.db.models import ExternalAppUserCredential
from onyx.db.models import Sandbox
from onyx.db.models import Skill
from onyx.db.models import Skill__User
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
from onyx.utils.logger import setup_logger

logger = setup_logger()

SKILL_SLUG_UNIQUE_CONSTRAINT = "uq_skill_slug"


class SkillAccessPolicy(str, Enum):
    VIEW = "view"
    EDIT = "edit"
    USE = "use"


@dataclass(frozen=True, kw_only=True)
class SkillPatch:
    is_public: bool | UnsetType = UNSET
    enabled: bool | UnsetType = UNSET


def _is_shared_with_user(
    user: User,
    permission: SkillSharePermission | None = None,
) -> ColumnElement[bool]:
    stmt = (
        select(Skill__User.skill_id)
        .where(Skill__User.skill_id == Skill.id)
        .where(Skill__User.user_id == user.id)
    )
    if permission is not None:
        stmt = stmt.where(Skill__User.permission == permission)
    return stmt.exists()


def _is_shared_with_user_group(
    user: User,
    permission: SkillSharePermission | None = None,
) -> ColumnElement[bool]:
    stmt = (
        select(Skill__UserGroup.skill_id)
        .join(
            User__UserGroup,
            User__UserGroup.user_group_id == Skill__UserGroup.user_group_id,
        )
        .where(Skill__UserGroup.skill_id == Skill.id)
        .where(User__UserGroup.user_id == user.id)
    )
    if permission is not None:
        stmt = stmt.where(Skill__UserGroup.permission == permission)
    return stmt.exists()


def _any_share_exists() -> ColumnElement[bool]:
    user_share_exists = (
        select(Skill__User.skill_id).where(Skill__User.skill_id == Skill.id).exists()
    )
    group_share_exists = (
        select(Skill__UserGroup.skill_id)
        .where(Skill__UserGroup.skill_id == Skill.id)
        .exists()
    )
    return or_(user_share_exists, group_share_exists)


def _personal_skill_clause(user_id: UUID) -> ColumnElement[bool]:
    """Predicate matching *user_id*'s personal skills: custom, non-public,
    zero direct/group shares, authored by the user."""
    no_shares = ~_any_share_exists()
    return and_(
        Skill.author_user_id == user_id,
        Skill.built_in_skill_id.is_(None),
        Skill.public_permission.is_(None),
        no_shares,
    )


def _is_group_shared_only_with_curator_scope(user: User) -> ColumnElement[bool]:
    """Curators can manage skills only when all group shares are in their scope."""
    curator_scope_group_ids = select(User__UserGroup.user_group_id).where(
        User__UserGroup.user_id == user.id
    )
    share_in_curator_scope_exists = (
        select(Skill__UserGroup.skill_id)
        .join(
            User__UserGroup,
            User__UserGroup.user_group_id == Skill__UserGroup.user_group_id,
        )
        .where(Skill__UserGroup.skill_id == Skill.id)
        .where(User__UserGroup.user_id == user.id)
    )

    if user.role == UserRole.CURATOR:
        curator_scope_group_ids = curator_scope_group_ids.where(
            User__UserGroup.is_curator.is_(True)
        )
        share_in_curator_scope_exists = share_in_curator_scope_exists.where(
            User__UserGroup.is_curator.is_(True)
        )

    no_group_share_outside_scope = ~exists().where(
        Skill__UserGroup.skill_id == Skill.id
    ).where(Skill__UserGroup.user_group_id.notin_(curator_scope_group_ids)).correlate(
        Skill
    )
    return and_(share_in_curator_scope_exists.exists(), no_group_share_outside_scope)


def all_skills_for_user_incl_external_apps(
    user: User, db_session: Session
) -> set[UUID]:
    """Enabled skill ids the user can see, including external-app-backed rows.

    Used by the external-app API to decide which apps a user may connect. This
    deliberately does not apply the per-user external-app credential gate.
    """
    stmt = (
        select(Skill.id)
        .where(Skill.enabled.is_(True))
        .where(
            or_(
                Skill.public_permission.isnot(None),
                _is_shared_with_user(user),
                _is_shared_with_user_group(user),
                and_(
                    Skill.author_user_id == user.id,
                    Skill.built_in_skill_id.is_(None),
                ),
            )
        )
    )
    return set(db_session.scalars(stmt))


def _exclude_unavailable_built_in_skills(
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


def _external_app_skill_ids_available_to_user(
    user: User, db_session: Session
) -> list[UUID]:
    """External-app-backed skill ids this user may load into their sandbox.

    Each external app is left-joined to this user's credential row; an app
    is available when it needs no per-user credentials, or when the user has
    already configured every required credential key.
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
        if is_user_authenticated_for_app(app, user_cred)
    ]


def _public_permission_for_update(
    *,
    current_permission: SkillSharePermission | None,
    is_public: bool | None,
    public_permission: SkillSharePermission | None,
) -> SkillSharePermission | None:
    if is_public is False:
        return None
    if public_permission is not None:
        return public_permission
    if is_public is True:
        return current_permission or SkillSharePermission.VIEWER
    return current_permission


def _skill_select_with_eager_load(*, order_by_name: bool) -> Select[tuple[Skill]]:
    stmt = select(Skill).options(
        selectinload(Skill.author),
        selectinload(Skill.user_shares).selectinload(Skill__User.user),
        selectinload(Skill.group_shares).selectinload(Skill__UserGroup.user_group),
    )
    if order_by_name:
        stmt = stmt.order_by(Skill.name)
    return stmt


def _skill_select_for_access_policy(
    *,
    policy: SkillAccessPolicy,
    db_session: Session,
    user: User,
    order_by_name: bool,
) -> Select[tuple[Skill]]:
    stmt = _skill_select_with_eager_load(order_by_name=order_by_name).outerjoin(
        ExternalApp,
        ExternalApp.skill_id == Skill.id,
    )
    owned_by_user = and_(
        Skill.author_user_id == user.id,
        Skill.built_in_skill_id.is_(None),
    )
    visible_to_user = or_(
        Skill.public_permission.isnot(None),
        _is_shared_with_user(user),
        _is_shared_with_user_group(user),
        owned_by_user,
    )
    editable_by_user = or_(
        owned_by_user,
        _is_shared_with_user(user, SkillSharePermission.EDITOR),
        _is_shared_with_user_group(user, SkillSharePermission.EDITOR),
        Skill.public_permission == SkillSharePermission.EDITOR,
    )

    if user.role in (UserRole.CURATOR, UserRole.GLOBAL_CURATOR):
        editable_by_user = or_(
            editable_by_user,
            _is_group_shared_only_with_curator_scope(user),
        )

    if policy == SkillAccessPolicy.VIEW:
        stmt = stmt.where(ExternalApp.id.is_(None))
        if user.role == UserRole.ADMIN:
            return stmt
        stmt = stmt.where(
            visible_to_user,
            or_(Skill.enabled.is_(True), editable_by_user),
        )
        return _exclude_unavailable_built_in_skills(
            stmt,
            db_session=db_session,
        )

    if policy == SkillAccessPolicy.EDIT:
        stmt = stmt.where(
            ExternalApp.id.is_(None),
            Skill.built_in_skill_id.is_(None),
        )
        if user.role == UserRole.ADMIN:
            return stmt
        return stmt.where(editable_by_user)

    if policy == SkillAccessPolicy.USE:
        available_external_app_skill_ids = _external_app_skill_ids_available_to_user(
            user, db_session
        )
        available_in_sandbox = or_(
            ExternalApp.id.is_(None),
            Skill.id.in_(available_external_app_skill_ids),
        )
        stmt = stmt.where(
            Skill.enabled.is_(True),
            available_in_sandbox,
            visible_to_user,
        )
        return _exclude_unavailable_built_in_skills(stmt, db_session)

    raise ValueError(f"Unknown skill access policy: {policy}")


def list_skills(
    *,
    policy: SkillAccessPolicy,
    db_session: Session,
    user: User,
) -> Sequence[Skill]:
    stmt = _skill_select_for_access_policy(
        policy=policy,
        db_session=db_session,
        user=user,
        order_by_name=True,
    )
    return list(db_session.scalars(stmt))


def fetch_skill(
    skill_id: UUID,
    *,
    policy: SkillAccessPolicy,
    db_session: Session,
    user: User,
) -> Skill | None:
    stmt = _skill_select_for_access_policy(
        policy=policy,
        db_session=db_session,
        user=user,
        order_by_name=False,
    ).where(Skill.id == skill_id)
    return db_session.scalars(stmt).one_or_none()


def list_skills_for_user(user: User, db_session: Session) -> Sequence[Skill]:
    """Skills the user sees in the skills endpoint.

    External-app-backed skills are excluded unconditionally — they're
    surfaced (and mutated) via the external-apps API only. Use
    ``list_skills_for_sandbox_injection`` to get the wider set the
    sandbox actually receives (which includes authenticated external
    apps).

    Disabled skills are hidden EXCEPT the user's own personal skills,
    which stay listed (greyed out in the UI) so the owner can re-enable
    them. Sandbox injection never includes disabled skills.
    """
    return list_skills(
        policy=SkillAccessPolicy.VIEW,
        user=user,
        db_session=db_session,
    )


def fetch_skill_for_user(
    skill_id: UUID, user: User, db_session: Session
) -> Skill | None:
    """Skill the user can read via the skills endpoint. Returns ``None``
    for external-app-backed rows even when the id matches — the skills
    endpoint must not be a mutation seam for external apps. Disabled
    skills resolve only for their owner (own-personal rows)."""
    return fetch_skill(
        skill_id,
        policy=SkillAccessPolicy.VIEW,
        user=user,
        db_session=db_session,
    )


def fetch_skill_for_user_by_slug(
    slug: str, user: User, db_session: Session
) -> Skill | None:
    """Slug variant of ``fetch_skill_for_user``. Same exclusion: never
    returns external-app-backed skills."""
    stmt = _skill_select_for_access_policy(
        policy=SkillAccessPolicy.VIEW,
        db_session=db_session,
        user=user,
        order_by_name=False,
    ).where(Skill.slug == slug)
    return db_session.scalars(stmt).one_or_none()


def fetch_skill_for_edit(
    skill_id: UUID, user: User, db_session: Session
) -> Skill | None:
    return fetch_skill(
        skill_id,
        policy=SkillAccessPolicy.EDIT,
        user=user,
        db_session=db_session,
    )


def list_skills_for_sandbox_injection(
    user: User, db_session: Session
) -> Sequence[Skill]:
    """Skills delivered into *user*'s sandbox: every regular skill they
    can see, plus the external-app-backed skills they've authenticated
    for. Used by the sandbox skill-push path, NOT by the skills
    endpoint (which excludes external apps entirely)."""
    return list_skills(
        policy=SkillAccessPolicy.USE,
        user=user,
        db_session=db_session,
    )


def fetch_skill_by_id(skill_id: UUID, db_session: Session) -> Skill | None:
    stmt = _skill_select_with_eager_load(order_by_name=False).where(
        Skill.id == skill_id
    )
    return db_session.scalars(stmt).one_or_none()


def list_skills_for_admin(db_session: Session) -> Sequence[Skill]:
    stmt = _skill_select_with_eager_load(order_by_name=True)
    return list(db_session.scalars(stmt))


def create_skill__no_commit(
    *,
    slug: str,
    name: str,
    description: str,
    bundle_file_id: str,
    bundle_sha256: str,
    is_public: bool,
    public_permission: SkillSharePermission | None = None,
    author_user_id: UUID | None,
    db_session: Session,
) -> Skill:
    skill = Skill(
        slug=slug,
        name=name,
        description=description,
        bundle_file_id=bundle_file_id,
        bundle_sha256=bundle_sha256,
        public_permission=_public_permission_for_update(
            current_permission=None,
            is_public=is_public,
            public_permission=public_permission,
        ),
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
    public_permission: SkillSharePermission | None = None,
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
    skill = Skill(
        slug=built_in_skill_id,
        name=name,
        description=description,
        built_in_skill_id=built_in_skill_id,
        bundle_file_id=None,
        bundle_sha256=None,
        public_permission=_public_permission_for_update(
            current_permission=None,
            is_public=is_public,
            public_permission=public_permission,
        ),
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
    """Swap a skill's bundle blob and refresh its display metadata.

    Returns ``(skill, old_bundle_file_id)`` so the caller can delete the
    old blob from FileStore AFTER the transaction commits — never
    inline.

    Name and description come from the new bundle's SKILL.md frontmatter so
    the DB row stays in lockstep with what's actually pushed to sandboxes.

    Rejects built-in rows — they have no bundle.
    """
    skill = fetch_skill_by_id(skill_id, db_session)
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


def update_skill_fields(
    *,
    skill: Skill,
    db_session: Session,
    is_public: bool | None = None,
    public_permission: SkillSharePermission | None = None,
    enabled: bool | None = None,
) -> Skill:
    if is_public is not None or public_permission is not None:
        skill.public_permission = _public_permission_for_update(
            current_permission=skill.public_permission,
            is_public=is_public,
            public_permission=public_permission,
        )
    if enabled is not None:
        skill.enabled = enabled

    db_session.flush()
    return skill


def patch_skill(
    *,
    skill_id: UUID,
    patch: SkillPatch,
    db_session: Session,
) -> Skill:
    skill = fetch_skill_by_id(skill_id, db_session)
    if skill is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"Skill {skill_id} not found.",
        )

    return update_skill_fields(
        skill=skill,
        db_session=db_session,
        is_public=None if isinstance(patch.is_public, UnsetType) else patch.is_public,
        enabled=None if isinstance(patch.enabled, UnsetType) else patch.enabled,
    )


def replace_skill_shares(
    *,
    skill: Skill,
    db_session: Session,
    user_shares: Mapping[UUID, SkillSharePermission] | None = None,
    group_shares: Mapping[int, SkillSharePermission] | None = None,
) -> None:
    if user_shares is not None:
        db_session.execute(delete(Skill__User).where(Skill__User.skill_id == skill.id))
        for user_id, permission in user_shares.items():
            db_session.add(
                Skill__User(skill_id=skill.id, user_id=user_id, permission=permission)
            )

    if group_shares is not None:
        db_session.execute(
            delete(Skill__UserGroup).where(Skill__UserGroup.skill_id == skill.id)
        )
        for group_id, permission in group_shares.items():
            db_session.add(
                Skill__UserGroup(
                    skill_id=skill.id,
                    user_group_id=group_id,
                    permission=permission,
                )
            )

    try:
        db_session.flush()
    except IntegrityError as e:
        if is_fk_violation(e):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "One or more share targets do not exist.",
            ) from e
        raise


def transfer_skill_ownership(
    *,
    skill: Skill,
    new_owner_user_id: UUID,
    db_session: Session,
) -> None:
    if skill.built_in_skill_id is not None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Skill '{skill.slug}' is a built-in and cannot have its ownership transferred.",
        )

    previous_owner_user_id = skill.author_user_id
    if new_owner_user_id == previous_owner_user_id:
        return

    try:
        with db_session.no_autoflush:
            skill.author_user_id = new_owner_user_id

            db_session.execute(
                delete(Skill__User).where(
                    Skill__User.skill_id == skill.id,
                    Skill__User.user_id == new_owner_user_id,
                )
            )

            if previous_owner_user_id is not None:
                existing_share = db_session.scalar(
                    select(Skill__User).where(
                        Skill__User.skill_id == skill.id,
                        Skill__User.user_id == previous_owner_user_id,
                    )
                )
                if existing_share is not None:
                    existing_share.permission = SkillSharePermission.EDITOR
                else:
                    db_session.add(
                        Skill__User(
                            skill_id=skill.id,
                            user_id=previous_owner_user_id,
                            permission=SkillSharePermission.EDITOR,
                        )
                    )

        db_session.flush()
    except IntegrityError as e:
        if is_fk_violation(e):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "New owner user does not exist.",
            ) from e
        raise


def replace_skill_grants(
    skill_id: UUID, group_ids: Sequence[int], db_session: Session
) -> None:
    skill = fetch_skill_by_id(skill_id, db_session)
    if skill is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"Skill {skill_id} not found.",
        )
    group_shares: dict[int, SkillSharePermission] = {}
    for group_id in group_ids:
        group_shares.setdefault(group_id, SkillSharePermission.VIEWER)

    db_session.execute(
        delete(Skill__UserGroup).where(Skill__UserGroup.skill_id == skill.id)
    )
    for group_id, permission in group_shares.items():
        db_session.add(
            Skill__UserGroup(
                skill_id=skill.id,
                user_group_id=group_id,
                permission=permission,
            )
        )
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
    skill = fetch_skill_by_id(skill_id, db_session)
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
    if skill.public_permission is not None:
        stmt = select(Sandbox.user_id).where(Sandbox.status == SandboxStatus.RUNNING)
        return set(db_session.scalars(stmt))

    group_share_stmt = (
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
    user_ids = set(db_session.scalars(group_share_stmt))

    user_share_stmt = (
        select(Sandbox.user_id)
        .join(
            Skill__User,
            Skill__User.user_id == Sandbox.user_id,
        )
        .where(Skill__User.skill_id == skill.id)
        .where(Sandbox.status == SandboxStatus.RUNNING)
    )
    user_ids |= set(db_session.scalars(user_share_stmt))

    if skill.author_user_id is not None:
        author_stmt = (
            select(Sandbox.user_id)
            .where(Sandbox.user_id == skill.author_user_id)
            .where(Sandbox.status == SandboxStatus.RUNNING)
        )
        user_ids |= set(db_session.scalars(author_stmt))

    return user_ids


def count_personal_skills_for_user(user_id: UUID, db_session: Session) -> int:
    stmt = select(func.count(Skill.id)).where(_personal_skill_clause(user_id))
    return db_session.scalar(stmt) or 0


# Namespaced + user-hashed so unrelated users don't block each other and the
# lock id can't collide with other advisory locks in the codebase.
_PERSONAL_SKILL_LOCK_NAMESPACE = "onyx_personal_skill_lock"


def _personal_skill_lock_id(user_id: UUID) -> int:
    digest = hashlib.sha256(
        f"{_PERSONAL_SKILL_LOCK_NAMESPACE}:{user_id}".encode()
    ).digest()
    # Full 64-bit key (not 32-bit hashtext) so distinct users don't collide;
    # explicit big-endian so the id is stable across platforms.
    # pg_advisory_xact_lock takes a signed 8-byte int.
    return struct.unpack(">q", digest[:8])[0]


def lock_personal_skills_for_user(user_id: UUID, db_session: Session) -> None:
    """Serialize a user's concurrent personal-skill creates so the
    count-then-insert cap check is race-free; released at transaction end."""
    lock_id = _personal_skill_lock_id(user_id)
    logger.debug(
        "Acquiring personal-skill advisory lock for user %s (lock_id=%d)",
        user_id,
        lock_id,
    )
    db_session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": lock_id},
    )
    logger.debug("Acquired personal-skill advisory lock for user %s", user_id)


def skill_ids_with_grants(skill_ids: Sequence[UUID], db_session: Session) -> set[UUID]:
    """Subset of *skill_ids* that have at least one direct or group share row."""
    if not skill_ids:
        return set()

    group_share_stmt = (
        select(Skill__UserGroup.skill_id)
        .where(Skill__UserGroup.skill_id.in_(skill_ids))
        .distinct()
    )
    user_share_stmt = (
        select(Skill__User.skill_id)
        .where(Skill__User.skill_id.in_(skill_ids))
        .distinct()
    )
    return set(db_session.scalars(group_share_stmt)) | set(
        db_session.scalars(user_share_stmt)
    )


def get_group_ids_for_skill(skill_id: UUID, db_session: Session) -> list[int]:
    stmt = select(Skill__UserGroup.user_group_id).where(
        Skill__UserGroup.skill_id == skill_id
    )
    return list(db_session.scalars(stmt))
