from uuid import UUID

from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission, has_permission
from onyx.auth.scoped_permissions import assert_within_scope
from onyx.db.enums import Permission, PermissionAuthority, PersonaSharePermission
from onyx.db.models import Persona, Persona__UserGroup, User
from onyx.db.persona import (
    _transfer_persona_ownership,
    apply_persona_user_share_diff,
    can_delete_persona,
    mark_persona_user_files_for_sync,
    resolve_desired_user_shares,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


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
    """Reconcile persona__user_group rows to ``desired_shares`` — delete missing, update
    changed levels in place, insert new rows. Callers must hold the agent's row lock: this
    re-reads the rows the scope gate ran on."""
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


def _assert_group_share_within_scope(
    acting_user: User,
    persona_id: int,
    desired_group_shares: dict[int, PersonaSharePermission],
    db_session: Session,
    original_is_public: bool,
) -> None:
    """GATE 2: *changing* an agent's group shares is a MANAGE_AGENTS action. Global
    holders bypass; a scoped manager may only add/remove groups they manage on a PRIVATE
    agent; anyone else may leave the shares alone but not alter them. Shares are re-read
    in-txn, never the caller's, so a reassignment can't escape scope — and under the
    caller's row lock, so the write reconciles this same snapshot. Both the pre-call and
    current is_public must be private — sharing a public agent in would capture it."""
    # A global groups admin administers every group, so group shares are theirs to set —
    # same bypass _assert_group_update_within_scope takes for cc_pairs. Which agents they
    # may touch is still gated by the caller's fetch.
    if has_global_permission(acting_user, Permission.MANAGE_USER_GROUPS):
        return
    current_shares = {
        row.user_group_id: row.permission
        for row in db_session.query(Persona__UserGroup)
        .filter(Persona__UserGroup.persona_id == persona_id)
        .all()
    }
    # No group either side: a personal agent, nothing to authorize. Keeps groups=[]
    # creates open to an ADD_AGENTS-only user.
    if not current_shares and not desired_group_shares:
        return
    persona = db_session.query(Persona).filter(Persona.id == persona_id).first()
    if persona is None:
        raise OnyxError(
            OnyxErrorCode.PERSONA_NOT_FOUND, f"Persona {persona_id} does not exist"
        )
    owns_agent = can_delete_persona(acting_user, persona, db_session)
    # Scope governs which groups an agent reaches, not the level within them; adding or
    # removing a group still falls through to the gate.
    if owns_agent and set(current_shares) == set(desired_group_shares):
        return
    # Untouched shares aren't a mutation: the editor round-trips current groups on save.
    if current_shares == desired_group_shares and (
        has_permission(acting_user, Permission.MANAGE_AGENTS)
        is not PermissionAuthority.SCOPED
    ):
        return
    assert_within_scope(
        acting_user,
        db_session,
        permission=Permission.MANAGE_AGENTS,
        current_group_ids=list(current_shares),
        requested_group_ids=list(desired_group_shares),
        is_non_public=not original_is_public and not persona.is_public,
    )


def update_persona_access(
    persona_id: int,
    creator_user_id: UUID | None,
    db_session: Session,
    acting_user: User,
    is_public: bool | None = None,
    user_ids: list[UUID] | None = None,
    group_ids: list[int] | None = None,
    user_shares: dict[UUID, PersonaSharePermission] | None = None,
    group_shares: dict[int, PersonaSharePermission] | None = None,
    public_permission: PersonaSharePermission | None = None,
    original_is_public: bool | None = None,
) -> None:
    """EE version of the MIT function: identical semantics plus group-share
    support.

    Pass ``original_is_public`` if you changed is_public before calling: autoflush writes
    the pending value before the read below, so deriving it here reads back the new state.

    NOTE: Callers are responsible for committing."""
    needs_sync = False
    # Lock the agent so the gate and _apply_persona_group_share_diff can't be split by a
    # concurrent save; populate_existing refreshes the caller's already-loaded row, which
    # would otherwise serve pre-lock is_public out of the identity map.
    persona = (
        db_session.query(Persona)
        .populate_existing()
        .filter(Persona.id == persona_id)
        .with_for_update()
        .first()
    )
    if original_is_public is None:
        original_is_public = persona.is_public if persona is not None else False

    if is_public is not None or public_permission is not None:
        needs_sync = True
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
        _assert_group_share_within_scope(
            acting_user,
            persona_id,
            desired_group_shares,
            db_session,
            original_is_public,
        )
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
