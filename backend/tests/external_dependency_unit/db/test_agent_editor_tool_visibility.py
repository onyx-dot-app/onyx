"""Regression coverage for `get_tool_ids_on_editable_personas`.

The agent editor rebuilds an agent's `tool_ids` from the actions listing, so an
action it cannot see is one the next save drops. An editor must therefore see the
actions on an agent they can edit — and nothing more, since the same set widens the
read gate on the action-management surfaces.
"""

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.configs.constants import ANONYMOUS_USER_UUID
from onyx.db.enums import PersonaSharePermission
from onyx.db.models import Persona, Persona__Tool, Tool, User
from onyx.db.persona import get_tool_ids_on_editable_personas, mark_persona_as_deleted
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.db.agent_sharing_helpers import (
    create_test_persona,
    create_test_user_group,
    share_persona_with_group,
    share_persona_with_user,
)


def _create_tool(db_session: Session, owner: User | None) -> Tool:
    tool = Tool(
        name=f"editor-visibility-tool-{uuid4().hex[:8]}",
        description="editor visibility test action",
        in_code_tool_id=None,
        openapi_schema={"openapi": "3.0.0"},
        custom_headers=[],
        user_id=owner.id if owner else None,
        passthrough_auth=False,
    )
    db_session.add(tool)
    db_session.commit()
    db_session.refresh(tool)
    return tool


def _attach(db_session: Session, persona: Persona, tool: Tool) -> None:
    db_session.add(Persona__Tool(persona_id=persona.id, tool_id=tool.id))
    db_session.commit()


def test_owner_sees_tool_attached_to_own_agent(db_session: Session) -> None:
    owner = create_test_user(db_session, "editor_owner")
    admin = create_test_user(db_session, "editor_admin", is_admin=True)

    persona = create_test_persona(db_session, owner=owner)
    attached = _create_tool(db_session, owner=admin)
    _attach(db_session, persona, attached)

    assert attached.id in get_tool_ids_on_editable_personas(owner, db_session)


def test_unattached_tool_stays_hidden(db_session: Session) -> None:
    owner = create_test_user(db_session, "editor_owner_neg")
    admin = create_test_user(db_session, "editor_admin_neg", is_admin=True)

    create_test_persona(db_session, owner=owner)
    unattached = _create_tool(db_session, owner=admin)

    assert unattached.id not in get_tool_ids_on_editable_personas(owner, db_session)


def test_tool_on_someone_elses_agent_stays_hidden(db_session: Session) -> None:
    outsider = create_test_user(db_session, "editor_outsider")
    other_owner = create_test_user(db_session, "editor_other_owner")

    other_persona = create_test_persona(db_session, owner=other_owner)
    elsewhere = _create_tool(db_session, owner=other_owner)
    _attach(db_session, other_persona, elsewhere)

    assert elsewhere.id not in get_tool_ids_on_editable_personas(outsider, db_session)


def test_viewer_share_does_not_expose_tool(db_session: Session) -> None:
    """VIEWER grants use, not edit — a viewer never rebuilds the agent's tool list."""
    owner = create_test_user(db_session, "editor_share_owner")
    viewer = create_test_user(db_session, "editor_viewer")

    persona = create_test_persona(db_session, owner=owner)
    tool = _create_tool(db_session, owner=owner)
    _attach(db_session, persona, tool)
    share_persona_with_user(db_session, persona, viewer, PersonaSharePermission.VIEWER)

    assert tool.id not in get_tool_ids_on_editable_personas(viewer, db_session)


def test_editor_share_exposes_tool(db_session: Session) -> None:
    owner = create_test_user(db_session, "editor_share_owner_pos")
    editor = create_test_user(db_session, "editor_editor")

    persona = create_test_persona(db_session, owner=owner)
    tool = _create_tool(db_session, owner=owner)
    _attach(db_session, persona, tool)
    share_persona_with_user(db_session, persona, editor, PersonaSharePermission.EDITOR)

    assert tool.id in get_tool_ids_on_editable_personas(editor, db_session)


def test_group_editor_share_exposes_tool(db_session: Session) -> None:
    owner = create_test_user(db_session, "editor_group_owner")
    member = create_test_user(db_session, "editor_group_member")
    group = create_test_user_group(db_session, members=[member])

    persona = create_test_persona(db_session, owner=owner)
    tool = _create_tool(db_session, owner=owner)
    _attach(db_session, persona, tool)
    share_persona_with_group(db_session, persona, group, PersonaSharePermission.EDITOR)

    assert tool.id in get_tool_ids_on_editable_personas(member, db_session)


def test_deleted_agent_does_not_expose_tool(db_session: Session) -> None:
    """Soft-delete keeps the persona__tool rows, so the subquery has to drop the
    agent itself — otherwise a deleted agent keeps widening the action read gate."""
    owner = create_test_user(db_session, "editor_deleted_owner")

    persona = create_test_persona(db_session, owner=owner)
    tool = _create_tool(db_session, owner=owner)
    _attach(db_session, persona, tool)
    mark_persona_as_deleted(persona.id, owner, db_session)

    assert tool.id not in get_tool_ids_on_editable_personas(owner, db_session)


def test_deleted_agent_does_not_expose_tool_to_admin(db_session: Session) -> None:
    """MANAGE_AGENTS short-circuits the user filters entirely, so the deleted check
    cannot live inside them."""
    admin = create_test_user(db_session, "editor_deleted_admin", is_admin=True)

    persona = create_test_persona(db_session, owner=admin)
    tool = _create_tool(db_session, owner=admin)
    _attach(db_session, persona, tool)
    mark_persona_as_deleted(persona.id, admin, db_session)

    assert tool.id not in get_tool_ids_on_editable_personas(admin, db_session)


def test_anonymous_user_sees_nothing(db_session: Session) -> None:
    """`is_anonymous` keys on the seeded ANONYMOUS_USER_UUID row, so this must use that
    user — one built with an ANONYMOUS account_type is not anonymous to the filter, and
    the assertion would pass vacuously."""
    anonymous = db_session.scalar(
        select(User).where(
            User.id == UUID(ANONYMOUS_USER_UUID)  # ty: ignore[invalid-argument-type]
        )
    )
    assert anonymous is not None, "seeded anonymous user row is missing"
    assert anonymous.is_anonymous

    admin = create_test_user(db_session, "editor_anon_admin", is_admin=True)
    # public + listed is what the short-circuit would hand back as editable
    public_persona = create_test_persona(
        db_session, owner=admin, is_public=True, is_listed=True
    )
    tool = _create_tool(db_session, owner=admin)
    _attach(db_session, public_persona, tool)

    assert get_tool_ids_on_editable_personas(anonymous, db_session) == set()
