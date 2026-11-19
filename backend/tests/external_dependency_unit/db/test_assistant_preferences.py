"""The per-agent tool and integration choices of a user, checked against
Postgres."""

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
    try:
        update_assistant_preferences_for_user_api(
            DEFAULT_PERSONA_ID,
            UserSpecificAssistantPreference(
                disabled_tool_ids=[7], disabled_integration_ids=[3]
            ),
            user,
            db_session,
        )
        preferences = get_user_assistant_preferences(user, db_session)
        assert preferences is not None
        saved = preferences[DEFAULT_PERSONA_ID]
        assert (saved.disabled_tool_ids, saved.disabled_integration_ids) == ([7], [3])

        def saved_lists() -> tuple[list[int] | None, list[int] | None]:
            preferences = get_user_assistant_preferences(user, db_session)
            assert preferences is not None
            saved = preferences[DEFAULT_PERSONA_ID]
            return saved.disabled_tool_ids, saved.disabled_integration_ids

        # A tool-only write keeps the integrations.
        update_assistant_preferences_for_user_api(
            DEFAULT_PERSONA_ID,
            UserSpecificAssistantPreference(disabled_tool_ids=[8]),
            user,
            db_session,
        )
        assert saved_lists() == ([8], [3])
        # An integration-only write keeps the tools.
        update_assistant_preferences_for_user_api(
            DEFAULT_PERSONA_ID,
            UserSpecificAssistantPreference(disabled_integration_ids=[]),
            user,
            db_session,
        )
        assert saved_lists() == ([8], [])

        # The released mobile app writes and reads the ids as text.
        update_assistant_preferences_for_user_api(
            DEFAULT_PERSONA_ID,
            UserSpecificAssistantPreference.model_validate(
                {"disabled_tool_ids": [8], "disabled_plugin_ids": ["3", "5"]}
            ),
            user,
            db_session,
        )
        preferences = get_user_assistant_preferences(user, db_session)
        assert preferences is not None
        saved = preferences[DEFAULT_PERSONA_ID]
        assert saved.disabled_integration_ids == [3, 5]
        assert saved.model_dump()["disabled_plugin_ids"] == ["3", "5"]

        # A plugin id from before the upgrade maps to no integration, so the
        # write keeps the saved integrations.
        update_assistant_preferences_for_user_api(
            DEFAULT_PERSONA_ID,
            UserSpecificAssistantPreference.model_validate(
                {
                    "disabled_tool_ids": [9],
                    "disabled_plugin_ids": [
                        "3",
                        "0b5ad3f4-5d7e-4f42-9a51-0e8f1c2b7d6a",
                    ],
                }
            ),
            user,
            db_session,
        )
        assert saved_lists() == ([9], [3, 5])
    finally:
        db_session.rollback()
        db_session.execute(
            delete(Assistant__UserSpecificConfig).where(
                Assistant__UserSpecificConfig.user_id == user.id
            )
        )
        db_session.commit()
