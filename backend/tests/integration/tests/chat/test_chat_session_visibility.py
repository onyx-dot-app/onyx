"""Never-used ("failed") chat sessions are returned by the sidebar endpoint.

GET /chat/get-user-chat-sessions used to hide sessions whose only messages
are SYSTEM messages. That filter is gone: what exists is what is returned —
a never-used session shows up with name=null — and background GC reclaims
stale husks instead. Pagination semantics (page_size, before, has_more) are
unchanged.
"""

import pytest

from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.reset import reset_all
from tests.integration.common_utils.test_models import DATestLLMProvider, DATestUser

_MOCK_RESPONSE = "Mocked LLM response"


@pytest.fixture(scope="module", autouse=True)
def reset_for_module() -> None:
    """Reset all data once before running any tests in this module."""
    reset_all()


@pytest.fixture
def llm_provider(admin_user: DATestUser) -> DATestLLMProvider:
    return LLMProviderManager.create(user_performing_action=admin_user)


def test_never_used_session_is_listed_with_null_name(
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    husk = ChatSessionManager.create(
        user_performing_action=basic_user, description=None
    )

    used_session = ChatSessionManager.create(
        user_performing_action=basic_user, description="used session"
    )
    response = ChatSessionManager.send_message(
        chat_session_id=used_session.id,
        message="Hi",
        user_performing_action=basic_user,
        mock_llm_response=_MOCK_RESPONSE,
    )
    assert response.error is None

    listing = ChatSessionManager.get_user_chat_sessions(basic_user)
    sessions_by_id = {session["id"]: session for session in listing["sessions"]}

    assert str(used_session.id) in sessions_by_id
    assert str(husk.id) in sessions_by_id
    # create-chat-session coerces a null description to "" — either way the
    # husk has no user-visible name and the sidebar renders "Unnamed chat".
    assert not sessions_by_id[str(husk.id)]["name"]


def test_pagination_unchanged(
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    created_ids: list[str] = []
    for i in range(4):
        chat_session = ChatSessionManager.create(
            user_performing_action=basic_user, description=f"paginated {i}"
        )
        created_ids.append(str(chat_session.id))
        response = ChatSessionManager.send_message(
            chat_session_id=chat_session.id,
            message="Hi",
            user_performing_action=basic_user,
            mock_llm_response=_MOCK_RESPONSE,
        )
        assert response.error is None

    first_page = ChatSessionManager.get_user_chat_sessions(basic_user, page_size=2)
    assert len(first_page["sessions"]) == 2
    assert first_page["has_more"] is True

    # Walk the keyset pages; every created session must appear exactly once
    # and pages must be time_updated-descending.
    seen_ids: list[str] = []
    before: str | None = None
    while True:
        page = ChatSessionManager.get_user_chat_sessions(
            basic_user, page_size=2, before=before
        )
        sessions = page["sessions"]
        assert len(sessions) <= 2
        timestamps = [session["time_updated"] for session in sessions]
        assert timestamps == sorted(timestamps, reverse=True)
        seen_ids.extend(session["id"] for session in sessions)
        if not page["has_more"]:
            break
        before = sessions[-1]["time_updated"]

    assert len(seen_ids) == len(set(seen_ids))
    for session_id in created_ids:
        assert session_id in seen_ids
