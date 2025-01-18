from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest

from onyx.configs.constants import QAFeedbackType
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.query_history import QueryHistoryManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DAQueryHistoryEntry
from tests.integration.common_utils.test_models import DATestUser


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


def create_chat_session_with_feedback(
    admin_user: DATestUser,
    i: int,
    feedback_type: QAFeedbackType | None,
) -> tuple[QAFeedbackType | None, DAQueryHistoryEntry]:
    print(f"Creating chat session {i} with feedback type {feedback_type}")
    # Create chat session with timestamp spread over 30 days
    chat_session = ChatSessionManager.create(
        persona_id=0,
        description=f"Test chat session {i}",
        user_performing_action=admin_user,
    )

    test_session = DAQueryHistoryEntry(
        id=chat_session.id,
        persona_id=0,
        description=f"Test chat session {i}",
        feedback_type=feedback_type,
    )

    # First message in chat
    ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message=f"Question {i}?",
        user_performing_action=admin_user,
    )

    messages = ChatSessionManager.get_chat_history(
        chat_session=chat_session,
        user_performing_action=admin_user,
    )
    if feedback_type == QAFeedbackType.MIXED or feedback_type == QAFeedbackType.DISLIKE:
        ChatSessionManager.create_chat_message_feedback(
            message_id=messages[-1].id,
            is_positive=False,
            user_performing_action=admin_user,
        )

    # Second message with different feedback types
    ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message=f"Follow up {i}?",
        user_performing_action=admin_user,
        parent_message_id=messages[-1].id,
    )

    # Get updated messages to get the ID of the second message
    messages = ChatSessionManager.get_chat_history(
        chat_session=chat_session,
        user_performing_action=admin_user,
    )
    if feedback_type == QAFeedbackType.MIXED or feedback_type == QAFeedbackType.LIKE:
        ChatSessionManager.create_chat_message_feedback(
            message_id=messages[-1].id,
            is_positive=True,
            user_performing_action=admin_user,
        )

    return feedback_type, test_session


@pytest.fixture
def setup_chat_session(
    reset: None,
) -> tuple[DATestUser, dict[QAFeedbackType | None, list[DAQueryHistoryEntry]]]:
    # Create admin user and required resources
    admin_user: DATestUser = UserManager.create(name="admin_user")
    cc_pair = CCPairManager.create_from_scratch(user_performing_action=admin_user)
    api_key = APIKeyManager.create(user_performing_action=admin_user)
    LLMProviderManager.create(user_performing_action=admin_user)

    # Seed a document
    cc_pair.documents = []
    cc_pair.documents.append(
        DocumentManager.seed_doc_with_content(
            cc_pair=cc_pair,
            content="The company's revenue in Q1 was $1M",
            api_key=api_key,
        )
    )

    chat_sessions_by_feedback_type: dict[
        QAFeedbackType | None, list[DAQueryHistoryEntry]
    ] = {}
    # Use ThreadPoolExecutor to create chat sessions in parallel
    with ThreadPoolExecutor(max_workers=5) as executor:
        # Submit all tasks and store futures
        j = 0
        number_of_sessions = 2
        futures = []
        for feedback_type in [
            QAFeedbackType.MIXED,
            QAFeedbackType.LIKE,
            QAFeedbackType.DISLIKE,
            None,
        ]:
            futures.extend(
                [
                    executor.submit(
                        create_chat_session_with_feedback,
                        admin_user,
                        (j * number_of_sessions) + i,
                        feedback_type,
                    )
                    for i in range(number_of_sessions)
                ]
            )
            j += 1

        # Collect results in order
        for future in as_completed(futures):
            feedback_type, chat_session = future.result()
            chat_sessions_by_feedback_type.setdefault(feedback_type, []).append(
                chat_session
            )

    return admin_user, chat_sessions_by_feedback_type


def test_query_history_pagination(
    setup_chat_session: tuple[
        DATestUser, dict[QAFeedbackType | None, list[DAQueryHistoryEntry]]
    ]
) -> None:
    admin_user, chat_sessions_by_feedback_type = setup_chat_session

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
