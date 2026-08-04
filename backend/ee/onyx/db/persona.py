from uuid import UUID

from sqlalchemy.orm import Session

from onyx.auth.permissions import has_permission
from onyx.auth.scoped_permissions import assert_within_scope
from onyx.db.enums import Permission
from onyx.db.enums import PermissionAuthority
from onyx.db.enums import PersonaSharePermission
from onyx.db.models import Persona
from onyx.db.models import Persona__UserGroup
from onyx.db.models import User
from onyx.db.persona import apply_persona_user_share_diff
from onyx.db.persona import mark_persona_user_files_for_sync
from onyx.db.persona import resolve_desired_user_shares
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
    in-txn, never trusted from the caller, so a reassignment can't escape scope. Privacy
    anchors on the original state too (snapshotted before is_public is applied) — a
    public→private convert in the same call must not slip past."""
    current_shares = {
        row.user_group_id: row.permission
        for row in db_session.query(Persona__UserGroup)
        .filter(Persona__UserGroup.persona_id == persona_id)
        .all()
    }
    # No group on either side: a personal agent, not a group-share mutation. Keeps
    # groups=[] creates open to an ADD_AGENTS-only user.
    if not current_shares and not desired_group_shares:
        return
    # Unchanged shares aren't a mutation either — the editor round-trips current groups
    # on every save, so otherwise a plain owner couldn't edit an agent someone else
    # group-shared. Levels count, not just ids. Scoped managers excluded: holding the
    # share while flipping the agent private is how a public agent gets captured.
    if (
        current_shares == desired_group_shares
        and has_permission(acting_user, Permission.MANAGE_AGENTS)
        is not PermissionAuthority.SCOPED
    ):
        return
    current_group_ids = list(current_shares)
    requested_group_ids = list(desired_group_shares)
    persona = db_session.query(Persona).filter(Persona.id == persona_id).first()
    if persona is None:
        raise OnyxError(
            OnyxErrorCode.PERSONA_NOT_FOUND, f"Persona {persona_id} does not exist"
        )
    assert_within_scope(
        acting_user,
        db_session,
        permission=Permission.MANAGE_AGENTS,
        current_group_ids=current_group_ids,
        requested_group_ids=requested_group_ids,
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
) -> None:
    """EE version of the MIT function: identical semantics plus group-share
    support.

    NOTE: Callers are responsible for committing."""
    needs_sync = False
    # Snapshot privacy before is_public is applied below, so the group-share gate
    # anchors on the ORIGINAL state — a public->private convert + group-share in one
    # call must not read the already-mutated (private) value and slip through.
    persona = db_session.query(Persona).filter(Persona.id == persona_id).first()
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
