"""EE regression coverage for group-based agent sharing: owner groups grant
every member full owner rights, leveled group shares gate edit access, group
ownership transfers, and group deletion orphans or deletes owned personas."""

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ee.onyx.db.persona import transfer_persona_ownership as ee_transfer
from ee.onyx.db.persona import update_persona_access as ee_update_persona_access
from ee.onyx.db.user_group import _handle_owned_personas_for_group_deletion__no_commit
from onyx.db.enums import PersonaAccessLevel
from onyx.db.enums import PersonaSharePermission
from onyx.db.enums import PersonaSharingStatus
from onyx.db.models import Persona
from onyx.db.models import Persona__UserGroup
from onyx.db.models import User
from onyx.db.persona import fetch_persona_by_id_for_user
from onyx.db.persona_sharing import derive_persona_sharing_status
from onyx.db.persona_sharing import get_persona_access_level
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.db.agent_sharing_helpers import create_test_persona
from tests.external_dependency_unit.db.agent_sharing_helpers import (
    create_test_user_group,
)
from tests.external_dependency_unit.db.agent_sharing_helpers import (
    share_persona_with_group,
)

pytestmark = pytest.mark.usefixtures("enable_ee")


def _can_edit(db_session: Session, persona_id: int, user: User) -> bool:
    try:
        fetch_persona_by_id_for_user(
            db_session=db_session, persona_id=persona_id, user=user, get_editable=True
        )
        return True
    except HTTPException:
        return False


def test_owner_group_members_get_owner_access(db_session: Session) -> None:
    member = create_test_user(db_session, "member")
    outsider = create_test_user(db_session, "outsider")
    group = create_test_user_group(db_session, members=[member])
    persona = create_test_persona(db_session, owner=None, owner_group_id=group.id)
    db_session.refresh(persona)

    assert _can_edit(db_session, persona.id, member)
    assert not _can_edit(db_session, persona.id, outsider)
    assert (
        get_persona_access_level(persona, member, {group.id})
        == PersonaAccessLevel.OWNER
    )
    # Group-owned but unshared still reads as SHARED, not PRIVATE (ENG-4175)
    assert derive_persona_sharing_status(persona) == PersonaSharingStatus.SHARED


def test_group_share_levels_gate_edit(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    member = create_test_user(db_session, "member")
    group = create_test_user_group(db_session, members=[member])

    viewer_persona = create_test_persona(db_session, owner)
    share_persona_with_group(
        db_session, viewer_persona, group, PersonaSharePermission.VIEWER
    )
    editor_persona = create_test_persona(db_session, owner)
    share_persona_with_group(
        db_session, editor_persona, group, PersonaSharePermission.EDITOR
    )

    assert not _can_edit(db_session, viewer_persona.id, member)
    assert _can_edit(db_session, editor_persona.id, member)


def test_ee_transfer_to_group(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    member = create_test_user(db_session, "member")
    group = create_test_user_group(db_session, members=[member])
    persona = create_test_persona(db_session, owner)
    share_persona_with_group(db_session, persona, group, PersonaSharePermission.VIEWER)

    ee_transfer(
        persona_id=persona.id,
        user=owner,
        db_session=db_session,
        new_owner_group_id=group.id,
    )
    db_session.refresh(persona)

    assert persona.owner_group_id == group.id
    assert persona.user_id is None
    # The owning group's share row is removed; the previous owner keeps EDITOR
    group_rows = (
        db_session.query(Persona__UserGroup)
        .filter(Persona__UserGroup.persona_id == persona.id)
        .all()
    )
    assert all(row.user_group_id != group.id for row in group_rows)
    assert any(
        share.user_id == owner.id and share.permission == PersonaSharePermission.EDITOR
        for share in persona.user_shares
    )


def test_ee_group_share_diff_updates_levels_in_place(db_session: Session) -> None:
    owner = create_test_user(db_session, "owner")
    member = create_test_user(db_session, "member")
    group = create_test_user_group(db_session, members=[member])
    persona = create_test_persona(db_session, owner)
    share_persona_with_group(db_session, persona, group, PersonaSharePermission.VIEWER)

    ee_update_persona_access(
        persona_id=persona.id,
        creator_user_id=owner.id,
        db_session=db_session,
        group_shares={group.id: PersonaSharePermission.EDITOR},
    )
    db_session.commit()

    row = (
        db_session.query(Persona__UserGroup)
        .filter(
            Persona__UserGroup.persona_id == persona.id,
            Persona__UserGroup.user_group_id == group.id,
        )
        .one()
    )
    assert row.permission == PersonaSharePermission.EDITOR


def test_group_deletion_orphans_shared_and_deletes_private(
    db_session: Session,
) -> None:
    member = create_test_user(db_session, "member")
    group = create_test_user_group(db_session, members=[member])

    private_persona = create_test_persona(
        db_session, owner=None, owner_group_id=group.id
    )
    public_persona = create_test_persona(
        db_session, owner=None, owner_group_id=group.id, is_public=True
    )

    _handle_owned_personas_for_group_deletion__no_commit(
        db_session=db_session, user_group_id=group.id
    )
    db_session.commit()

    private_after = db_session.get(Persona, private_persona.id)
    public_after = db_session.get(Persona, public_persona.id)
    assert private_after is not None and private_after.deleted
    assert public_after is not None and not public_after.deleted
    assert public_after.owner_group_id is None
