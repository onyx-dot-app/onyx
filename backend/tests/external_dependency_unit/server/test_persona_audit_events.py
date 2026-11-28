"""Agent events record the sharing state that was saved, not the request."""

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import PersonaSharePermission
from onyx.server.features.persona.api import PersonaShareRequest, share_persona
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.db.agent_sharing_helpers import (
    create_test_persona,
    share_persona_with_user,
)
from tests.utils.audit import events_for

pytestmark = pytest.mark.usefixtures("tenant_context", "audit_stream")


def test_share_event_shows_the_saved_state(
    db_session: Session,
    make_test_user: MakeTestUser,
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner = make_test_user("persona-audit-owner")
    editor = make_test_user("persona-audit-editor")
    persona = create_test_persona(db_session, owner)
    share_persona_with_user(db_session, persona, editor, PersonaSharePermission.EDITOR)

    # An editor may change shares but not publish; the helper drops is_public.
    share_persona(
        persona_id=persona.id,
        persona_share_request=PersonaShareRequest(is_public=True),
        user=editor,
        db_session=db_session,
    )

    (event,) = events_for(caplog, "persona.update")
    assert event["extra"]["change"] == "share"
    assert event["extra"]["is_public"] is False
    assert event["extra"]["owner_user_id"] == str(owner.id)
    assert {
        "user_id": str(editor.id),
        "permission": PersonaSharePermission.EDITOR.value,
    } in event["extra"]["user_shares"]
