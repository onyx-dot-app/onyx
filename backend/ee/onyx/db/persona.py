from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.enums import PersonaSharePermission
from onyx.db.models import Persona
from onyx.db.models import Persona__UserGroup
from onyx.db.models import User
from onyx.db.persona import _transfer_persona_ownership
from onyx.db.persona import apply_persona_user_share_diff
from onyx.db.persona import mark_persona_user_files_for_sync
from onyx.db.persona import resolve_desired_user_shares


def _resolve_desired_group_shares(
    persona_id: int,
    group_ids: list[int] | None,
    group_shares: dict[int, PersonaSharePermission] | None,
    db_session: Session,
) -> dict[int, PersonaSharePermission] | None:
    """Legacy group ids keep an existing row's level (new rows default to
    VIEWER) so pre-permission callers can't downgrade editor groups."""
    if group_shares is not None:
        return dict(group_shares)
    if group_ids is None:
        return None
    existing = {
        row.user_group_id: row.permission
        for row in db_session.query(Persona__UserGroup)
        .filter(Persona__UserGroup.persona_id == persona_id)
        .all()
    }
    return {
        group_id: existing.get(group_id, PersonaSharePermission.VIEWER)
        for group_id in set(group_ids)
    }


def _apply_persona_group_share_diff(
    persona_id: int,
    desired_shares: dict[int, PersonaSharePermission],
    db_session: Session,
) -> None:
    """Reconcile persona__user_group rows to ``desired_shares`` — delete
    missing, update changed levels in place, insert new rows."""
    existing_rows = (
        db_session.query(Persona__UserGroup)
        .filter(Persona__UserGroup.persona_id == persona_id)
        .all()
    )
    existing_by_group = {row.user_group_id: row for row in existing_rows}

    for group_id, row in existing_by_group.items():
        if group_id not in desired_shares:
            db_session.delete(row)
        elif row.permission != desired_shares[group_id]:
            row.permission = desired_shares[group_id]

    for group_id, permission in desired_shares.items():
        if group_id not in existing_by_group:
            db_session.add(
                Persona__UserGroup(
                    persona_id=persona_id,
                    user_group_id=group_id,
                    permission=permission,
                )
            )


def update_persona_access(
    persona_id: int,
    creator_user_id: UUID | None,
    db_session: Session,
    is_public: bool | None = None,
    user_ids: list[UUID] | None = None,
    group_ids: list[int] | None = None,
    user_shares: dict[UUID, PersonaSharePermission] | None = None,
    group_shares: dict[int, PersonaSharePermission] | None = None,
    public_permission: PersonaSharePermission | None = None,
) -> None:
    """EE version of the MIT function: identical semantics plus group-share
    support.

    NOTE: Callers are responsible for committing."""
    needs_sync = False
    if is_public is not None or public_permission is not None:
        needs_sync = True
        persona = db_session.query(Persona).filter(Persona.id == persona_id).first()
        if persona:
            if is_public is not None:
                persona.is_public = is_public
            if public_permission is not None:
                persona.public_permission = public_permission

    # NOTE: For share inputs, `None` means "leave unchanged", empty means
    # "clear all shares", and non-empty means "replace with these shares".
    desired_user_shares = resolve_desired_user_shares(
        persona_id, user_ids, user_shares, db_session
    )
    if desired_user_shares is not None:
        needs_sync = True
        apply_persona_user_share_diff(
            persona_id, desired_user_shares, creator_user_id, db_session
        )

    desired_group_shares = _resolve_desired_group_shares(
        persona_id, group_ids, group_shares, db_session
    )
    if desired_group_shares is not None:
        needs_sync = True
        _apply_persona_group_share_diff(persona_id, desired_group_shares, db_session)

    # When sharing changes, user file ACLs need to be updated in the vector DB
    if needs_sync:
        mark_persona_user_files_for_sync(persona_id, db_session)


def transfer_persona_ownership(
    persona_id: int,
    user: User,
    db_session: Session,
    new_owner_user_id: UUID | None = None,
    new_owner_group_id: int | None = None,
) -> None:
    """EE version: additionally allows transferring ownership to a group."""
    _transfer_persona_ownership(
        persona_id=persona_id,
        user=user,
        db_session=db_session,
        new_owner_user_id=new_owner_user_id,
        new_owner_group_id=new_owner_group_id,
    )
