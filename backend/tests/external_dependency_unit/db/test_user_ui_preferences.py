"""UI preference reads tolerate corruption; writes repair it and retain valid settings."""

import pytest
from pydantic import JsonValue
from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.db.user_preferences import update_user_ui_preferences
from onyx.server.manage.models import UserInfo
from tests.external_dependency_unit.conftest import MakeTestUser


@pytest.mark.parametrize(
    "stored,expected_paste,expected_interrupt",
    [
        ({"paste_as_tile": True, "interrupt_on_send": True}, True, True),
        ({"paste_as_tile": True, "interrupt_on_send": "yes"}, True, False),
        ({"paste_as_tile": 1, "interrupt_on_send": True}, False, True),
        (None, False, False),
    ],
)
def test_user_preferences_read_and_repair(
    db_session: Session,
    make_test_user: MakeTestUser,
    stored: JsonValue,
    expected_paste: bool,
    expected_interrupt: bool,
) -> None:
    user = make_test_user("ui-preferences")
    user.ui_preferences = stored
    db_session.commit()
    db_session.expire_all()
    restored = db_session.get(User, user.id)
    assert restored is not None

    preferences = UserInfo.from_model(restored).preferences
    assert preferences.paste_as_tile is expected_paste
    assert preferences.interrupt_on_send is expected_interrupt

    update_user_ui_preferences(user.id, db_session, interrupt_on_send=True)
    db_session.refresh(restored)
    assert restored.ui_preferences == {
        "paste_as_tile": expected_paste,
        "interrupt_on_send": True,
    }
    update_user_ui_preferences(user.id, db_session, paste_as_tile=False)
    db_session.refresh(restored)
    assert restored.ui_preferences == {
        "paste_as_tile": False,
        "interrupt_on_send": True,
    }
