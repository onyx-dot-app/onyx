"""The per-agent tool and plugin choices of a user, checked against Postgres."""

from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.db.models import Assistant__UserSpecificConfig
from onyx.server.manage.models import UserSpecificAssistantPreference
from onyx.server.manage.users import (
    get_user_assistant_preferences,
    update_assistant_preferences_for_user_api,
)
from tests.external_dependency_unit.conftest import MakeTestUser


def test_a_write_keeps_each_list_that_it_leaves_out(
    db_session: Session, make_test_user: MakeTestUser
) -> None:
    user = make_test_user("assistant-preferences")
    plugin_id = uuid4()
    try:
        update_assistant_preferences_for_user_api(
            DEFAULT_PERSONA_ID,
            UserSpecificAssistantPreference(
                disabled_tool_ids=[7], disabled_plugin_ids=[plugin_id]
            ),
            user,
            db_session,
        )

        update_assistant_preferences_for_user_api(
            DEFAULT_PERSONA_ID,
            UserSpecificAssistantPreference(disabled_plugin_ids=[]),
            user,
            db_session,
        )
        update_assistant_preferences_for_user_api(
            DEFAULT_PERSONA_ID,
            UserSpecificAssistantPreference(disabled_tool_ids=[8]),
            user,
            db_session,
        )

        preferences = get_user_assistant_preferences(user, db_session)
        assert preferences == {
            DEFAULT_PERSONA_ID: UserSpecificAssistantPreference(
                disabled_tool_ids=[8], disabled_plugin_ids=[]
            )
        }
    finally:
        db_session.rollback()
        db_session.execute(
            delete(Assistant__UserSpecificConfig).where(
                Assistant__UserSpecificConfig.user_id == user.id
            )
        )
        db_session.commit()
