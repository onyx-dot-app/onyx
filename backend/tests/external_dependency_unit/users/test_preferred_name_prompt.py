"""The chat prompt addresses the user by their preferred name.

The full name stays in the prompt as its own line, so the model can still use
it, for example to match the user in documents.
"""

from sqlalchemy.orm import Session

from onyx.chat.prompt_utils import build_user_information_prompt
from onyx.db.memory import get_memories
from onyx.db.user_preferences import fetch_user_preferences
from tests.external_dependency_unit.conftest import (
    create_test_user,
    delete_test_user,
)


def test_preferred_name_addresses_the_user_and_keeps_the_full_name(
    db_session: Session,
) -> None:
    user = create_test_user(db_session, "preferred-name")
    user.personal_name = "Jonathan Smith"
    user.preferred_name = "Jon"
    db_session.commit()
    try:
        memory_context = get_memories(
            user, fetch_user_preferences(user, db_session), db_session
        )
        prompt = build_user_information_prompt(memory_context)

        assert "User name: Jon\n" in prompt
        assert "User full name: Jonathan Smith\n" in prompt
        assert memory_context.user_info.placeholder_values["name"] == "Jon"
    finally:
        delete_test_user(db_session, user)


def test_full_name_addresses_the_user_without_a_preferred_name(
    db_session: Session,
) -> None:
    user = create_test_user(db_session, "full-name-only")
    user.personal_name = "Jonathan Smith"
    db_session.commit()
    try:
        memory_context = get_memories(
            user, fetch_user_preferences(user, db_session), db_session
        )
        prompt = build_user_information_prompt(memory_context)

        assert "User name: Jonathan Smith\n" in prompt
        assert "User full name:" not in prompt
        assert memory_context.user_info.placeholder_values["name"] == "Jonathan Smith"
    finally:
        delete_test_user(db_session, user)
