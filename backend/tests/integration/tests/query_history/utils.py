from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor

from onyx.configs.constants import QAFeedbackType
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DAQueryHistoryEntry
from tests.integration.common_utils.test_models import DATestUser


def _create_chat_session_with_feedback(
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


def setup_chat_sessions_with_different_feedback() -> (
    tuple[DATestUser, dict[QAFeedbackType | None, list[DAQueryHistoryEntry]]]
):
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
        # Will result in 40 sessions
        number_of_sessions = 10
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
                        _create_chat_session_with_feedback,
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
