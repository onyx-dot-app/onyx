import os
from datetime import datetime

import pytest

from onyx.configs.constants import QAFeedbackType
from tests.integration.common_utils.managers.query_history import QueryHistoryManager
from tests.integration.common_utils.test_models import DAQueryHistoryEntry
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.query_history.utils import (
    setup_chat_sessions_with_different_feedback,
)


def _verify_query_history_pagination(
    chat_sessions: list[DAQueryHistoryEntry],
    page_size: int = 5,
    feedback_type: QAFeedbackType | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    user_performing_action: DATestUser | None = None,
) -> None:
    retrieved_sessions: list[str] = []

    for i in range(0, len(chat_sessions), page_size):
        paginated_result = QueryHistoryManager.get_query_history_page(
            page_num=i // page_size,
            page_size=page_size,
            feedback_type=feedback_type,
            start_time=start_time,
            end_time=end_time,
            user_performing_action=user_performing_action,
        )

        # Verify that the total items is equal to the length of the chat sessions list
        assert paginated_result.total_items == len(chat_sessions)
        # Verify that the number of items in the page is equal to the page size
        assert len(paginated_result.items) == min(page_size, len(chat_sessions) - i)
        # Add the retrieved chat sessions to the list of retrieved sessions
        retrieved_sessions.extend(
            [str(session.id) for session in paginated_result.items]
        )

    # Create a set of all the expected chat session IDs
    all_expected_sessions = set(str(session.id) for session in chat_sessions)
    # Create a set of all the retrieved chat session IDs
    all_retrieved_sessions = set(retrieved_sessions)

    # Verify that the set of retrieved sessions is equal to the set of expected sessions
    assert all_expected_sessions == all_retrieved_sessions


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Query history tests are enterprise only",
)
def test_query_history_pagination(reset: None) -> None:
    (
        admin_user,
        chat_sessions_by_feedback_type,
    ) = setup_chat_sessions_with_different_feedback()

    all_chat_sessions = []
    for _, chat_sessions in chat_sessions_by_feedback_type.items():
        all_chat_sessions.extend(chat_sessions)

    # Verify basic pagination with different page sizes
    print("Verifying basic pagination with page size 5")
    _verify_query_history_pagination(
        chat_sessions=all_chat_sessions,
        page_size=5,
        user_performing_action=admin_user,
    )
    print("Verifying basic pagination with page size 10")
    _verify_query_history_pagination(
        chat_sessions=all_chat_sessions,
        page_size=10,
        user_performing_action=admin_user,
    )

    print("Verifying pagination with feedback type LIKE")
    liked_sessions = chat_sessions_by_feedback_type[QAFeedbackType.LIKE]
    _verify_query_history_pagination(
        chat_sessions=liked_sessions,
        feedback_type=QAFeedbackType.LIKE,
        user_performing_action=admin_user,
    )

    print("Verifying pagination with feedback type DISLIKE")
    disliked_sessions = chat_sessions_by_feedback_type[QAFeedbackType.DISLIKE]
    _verify_query_history_pagination(
        chat_sessions=disliked_sessions,
        feedback_type=QAFeedbackType.DISLIKE,
        user_performing_action=admin_user,
    )

    print("Verifying pagination with feedback type MIXED")
    mixed_sessions = chat_sessions_by_feedback_type[QAFeedbackType.MIXED]
    _verify_query_history_pagination(
        chat_sessions=mixed_sessions,
        feedback_type=QAFeedbackType.MIXED,
        user_performing_action=admin_user,
    )

    # Test with a small page size to verify handling of partial pages
    print("Verifying pagination with page size 3")
    _verify_query_history_pagination(
        chat_sessions=all_chat_sessions,
        page_size=3,
        user_performing_action=admin_user,
    )

    # Test with a page size larger than the total number of items
    print("Verifying pagination with page size 50")
    _verify_query_history_pagination(
        chat_sessions=all_chat_sessions,
        page_size=50,
        user_performing_action=admin_user,
    )
