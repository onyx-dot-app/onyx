"""Pure helpers over loaded Persona share relations. Kept import-light so both
the persona db layer and the API snapshot models can use them without cycles."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.enums import PersonaAccessLevel
from onyx.db.enums import PersonaSharePermission
from onyx.db.enums import PersonaSharingStatus
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.db.models import User__UserGroup


def get_user_group_ids_for_user(db_session: Session, user_id: UUID) -> set[int]:
    return set(
        db_session.scalars(
            select(User__UserGroup.user_group_id).where(
                User__UserGroup.user_id == user_id
            )
        ).all()
    )


def get_curated_user_group_ids_for_user(db_session: Session, user_id: UUID) -> set[int]:
    return set(
        db_session.scalars(
            select(User__UserGroup.user_group_id)
            .where(User__UserGroup.user_id == user_id)
            .where(User__UserGroup.is_curator.is_(True))
        ).all()
    )


def persona_ownership_is_vacant(persona: Persona) -> bool:
    """True when no live owner holds the persona: both owner refs are NULL on
    a non-builtin persona, or the owning user is deactivated or gone. Vacant
    personas are managed (and transferable) by admins. Requires `persona.user`
    loaded."""
    if persona.builtin_persona:
        return False
    if persona.user_id is not None:
        return persona.user is None or not persona.user.is_active
    return persona.owner_group_id is None


def get_persona_access_level(
    persona: Persona,
    user: User,
    user_group_ids: set[int],
) -> PersonaAccessLevel | None:
    """Computed access for ``user`` over loaded share relations. OWNER outranks
    everything; admins report EDITOR on personas they don't own. Curators'
    group-attachment edit rights are not reflected here — this level drives
    the sharing UI, not the editable fetch."""
    if persona.user_id == user.id or (
        persona.owner_group_id is not None and persona.owner_group_id in user_group_ids
    ):
        return PersonaAccessLevel.OWNER
    if user.role == UserRole.ADMIN:
        return PersonaAccessLevel.EDITOR

    has_viewer_access = False
    for user_share in persona.user_shares:
        if user_share.user_id == user.id:
            if user_share.permission == PersonaSharePermission.EDITOR:
                return PersonaAccessLevel.EDITOR
            has_viewer_access = True
    for group_share in persona.group_shares:
        if group_share.user_group_id in user_group_ids:
            if group_share.permission == PersonaSharePermission.EDITOR:
                return PersonaAccessLevel.EDITOR
            has_viewer_access = True
    if persona.is_public:
        if persona.public_permission == PersonaSharePermission.EDITOR:
            return PersonaAccessLevel.EDITOR
        has_viewer_access = True
    return PersonaAccessLevel.VIEWER if has_viewer_access else None


def derive_persona_sharing_status(persona: Persona) -> PersonaSharingStatus:
    """PUBLIC > SHARED > PRIVATE; group ownership alone counts as SHARED."""
    if persona.is_public:
        return PersonaSharingStatus.PUBLIC
    if (
        persona.user_shares
        or persona.group_shares
        or persona.owner_group_id is not None
    ):
        return PersonaSharingStatus.SHARED
    return PersonaSharingStatus.PRIVATE
