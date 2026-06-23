"""Regression coverage for persona ownership transfer: owner-only authority,
target validation (no bots/service accounts/slack/inactive users, no groups in
MIT), previous-owner demotion to an EDITOR share row, and admin transfer of
vacant (orphaned) personas."""

from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.enums import AccountType
from onyx.db.enums import PersonaSharePermission
from onyx.db.models import Persona__User
from onyx.db.persona import transfer_persona_ownership
from onyx.db.persona_sharing import persona_ownership_is_vacant
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.db.agent_sharing_helpers import create_test_persona
from tests.external_dependency_unit.db.agent_sharing_helpers import (
    share_persona_with_user,
)


def _share_row(
    db_session: Session, persona_id: int, user_id: UUID
) -> Persona__User | None:
    return (
        db_session.query(Persona__User)
        .filter(
            Persona__User.persona_id == persona_id,
            Persona__User.user_id == user_id,
        )
        .one_or_none()
    )


def test_owner_transfers_to_user(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    new_owner = create_test_user(db_session, "newowner")
    persona = create_test_persona(db_session, owner)
    share_persona_with_user(
        db_session, persona, new_owner, PersonaSharePermission.VIEWER
    )

    transfer_persona_ownership(
        persona_id=persona.id,
        user=owner,
        db_session=db_session,
        new_owner_user_id=new_owner.id,
    )
    db_session.refresh(persona)

    assert persona.user_id == new_owner.id
    assert persona.owner_group_id is None
    # New owner is no longer a sharee
    assert _share_row(db_session, persona.id, new_owner.id) is None
    # Previous owner was demoted to an EDITOR share row
    prev_row = _share_row(db_session, persona.id, owner.id)
    assert prev_row is not None
    assert prev_row.permission == PersonaSharePermission.EDITOR


def test_transfer_upserts_existing_prev_owner_row(db_session: Session) -> None:
    """If the previous owner somehow already has a share row, transfer must
    upgrade it in place instead of violating the primary key."""
    owner = create_test_user(db_session, "owner")
    new_owner = create_test_user(db_session, "newowner")
    persona = create_test_persona(db_session, owner)
    share_persona_with_user(db_session, persona, owner, PersonaSharePermission.VIEWER)

    transfer_persona_ownership(
        persona_id=persona.id,
        user=owner,
        db_session=db_session,
        new_owner_user_id=new_owner.id,
    )

    prev_row = _share_row(db_session, persona.id, owner.id)
    assert prev_row is not None
    assert prev_row.permission == PersonaSharePermission.EDITOR


def test_editor_cannot_transfer(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    editor = create_test_user(db_session, "editor")
    target = create_test_user(db_session, "target")
    persona = create_test_persona(db_session, owner)
    share_persona_with_user(db_session, persona, editor, PersonaSharePermission.EDITOR)

    with pytest.raises(PermissionError):
        transfer_persona_ownership(
            persona_id=persona.id,
            user=editor,
            db_session=db_session,
            new_owner_user_id=target.id,
        )


def test_viewer_cannot_transfer(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    viewer = create_test_user(db_session, "viewer")
    target = create_test_user(db_session, "target")
    persona = create_test_persona(db_session, owner)
    share_persona_with_user(db_session, persona, viewer, PersonaSharePermission.VIEWER)

    with pytest.raises(PermissionError):
        transfer_persona_ownership(
            persona_id=persona.id,
            user=viewer,
            db_session=db_session,
            new_owner_user_id=target.id,
        )


def test_admin_cannot_transfer_owned_persona(db_session: Session) -> None:
    """ENG-4177: only owners transfer. Admin authority applies to vacant
    personas only."""
    owner = create_test_user(db_session, "owner")
    admin = create_test_user(db_session, "admin", role=UserRole.ADMIN)
    target = create_test_user(db_session, "target")
    persona = create_test_persona(db_session, owner)

    with pytest.raises(PermissionError):
        transfer_persona_ownership(
            persona_id=persona.id,
            user=admin,
            db_session=db_session,
            new_owner_user_id=target.id,
        )


def test_admin_transfers_vacant_persona(db_session: Session) -> None:
    admin = create_test_user(db_session, "admin", role=UserRole.ADMIN)
    target = create_test_user(db_session, "target")
    persona = create_test_persona(db_session, owner=None)
    db_session.refresh(persona)
    assert persona_ownership_is_vacant(persona)

    transfer_persona_ownership(
        persona_id=persona.id,
        user=admin,
        db_session=db_session,
        new_owner_user_id=target.id,
    )
    db_session.refresh(persona)
    assert persona.user_id == target.id


def test_basic_user_cannot_transfer_vacant_persona(db_session: Session) -> None:
    basic = create_test_user(db_session, "basic")
    target = create_test_user(db_session, "target")
    persona = create_test_persona(db_session, owner=None)

    with pytest.raises(PermissionError):
        transfer_persona_ownership(
            persona_id=persona.id,
            user=basic,
            db_session=db_session,
            new_owner_user_id=target.id,
        )


def test_deactivated_owner_makes_persona_admin_transferable(
    db_session: Session,
) -> None:
    owner = create_test_user(db_session, "owner")
    admin = create_test_user(db_session, "admin", role=UserRole.ADMIN)
    target = create_test_user(db_session, "target")
    persona = create_test_persona(db_session, owner)

    owner.is_active = False
    db_session.commit()
    db_session.refresh(persona)
    assert persona_ownership_is_vacant(persona)

    transfer_persona_ownership(
        persona_id=persona.id,
        user=admin,
        db_session=db_session,
        new_owner_user_id=target.id,
    )
    db_session.refresh(persona)
    assert persona.user_id == target.id


@pytest.mark.parametrize(
    "role,account_type",
    [
        (UserRole.SLACK_USER, AccountType.STANDARD),
        (UserRole.EXT_PERM_USER, AccountType.STANDARD),
        (UserRole.BASIC, AccountType.BOT),
        (UserRole.BASIC, AccountType.SERVICE_ACCOUNT),
    ],
)
def test_transfer_rejects_invalid_target_account(
    db_session: Session, role: UserRole, account_type: AccountType
) -> None:
    owner = create_test_user(db_session, "owner")
    target = create_test_user(
        db_session, "target", role=role, account_type=account_type
    )
    persona = create_test_persona(db_session, owner)

    with pytest.raises(ValueError):
        transfer_persona_ownership(
            persona_id=persona.id,
            user=owner,
            db_session=db_session,
            new_owner_user_id=target.id,
        )


def test_transfer_rejects_inactive_target(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    target = create_test_user(db_session, "target")
    target.is_active = False
    db_session.commit()
    persona = create_test_persona(db_session, owner)

    with pytest.raises(ValueError):
        transfer_persona_ownership(
            persona_id=persona.id,
            user=owner,
            db_session=db_session,
            new_owner_user_id=target.id,
        )


def test_transfer_to_group_rejected_in_mit(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    persona = create_test_persona(db_session, owner)

    with pytest.raises(NotImplementedError):
        transfer_persona_ownership(
            persona_id=persona.id,
            user=owner,
            db_session=db_session,
            new_owner_group_id=123,
        )


def test_transfer_requires_exactly_one_target(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    persona = create_test_persona(db_session, owner)

    with pytest.raises(ValueError):
        transfer_persona_ownership(
            persona_id=persona.id,
            user=owner,
            db_session=db_session,
        )


def test_transfer_rejects_builtin_persona(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    target = create_test_user(db_session, "target")
    persona = create_test_persona(db_session, owner, builtin_persona=True)

    with pytest.raises(ValueError):
        transfer_persona_ownership(
            persona_id=persona.id,
            user=owner,
            db_session=db_session,
            new_owner_user_id=target.id,
        )
