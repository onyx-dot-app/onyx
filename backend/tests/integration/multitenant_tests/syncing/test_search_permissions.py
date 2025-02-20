from onyx.db.models import UserRole
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestAPIKey
from tests.integration.common_utils.test_models import DATestCCPair
from tests.integration.common_utils.test_models import DATestChatSession
from tests.integration.common_utils.test_models import DATestUser


def test_multi_tenant_access_control(reset_multitenant: None) -> None:
    # Creating an admin user (first user created is automatically an admin and also proviions the tenant
    admin_user1: DATestUser = UserManager.create(
        email="admin@onyx-test.com",
    )

    assert UserManager.is_role(admin_user1, UserRole.ADMIN)

    # Create Tenant 2 and its Admin User
    admin_user2: DATestUser = UserManager.create(
        email="admin2@onyx-test.com",
    )
    assert UserManager.is_role(admin_user2, UserRole.ADMIN)

    # Create connectors for Tenant 1
    cc_pair_1: DATestCCPair = CCPairManager.create_from_scratch(
        user_performing_action=admin_user1,
    )
    api_key_1: DATestAPIKey = APIKeyManager.create(
        user_performing_action=admin_user1,
    )
    api_key_1.headers.update(admin_user1.headers)
    LLMProviderManager.create(user_performing_action=admin_user1)

    # Seed documents for Tenant 1
    cc_pair_1.documents = []
    doc1_tenant1 = DocumentManager.seed_doc_with_content(
        cc_pair=cc_pair_1,
        content="Tenant 1 Document Content",
        api_key=api_key_1,
    )
    doc2_tenant1 = DocumentManager.seed_doc_with_content(
        cc_pair=cc_pair_1,
        content="Tenant 1 Document Content",
        api_key=api_key_1,
    )
    cc_pair_1.documents.extend([doc1_tenant1, doc2_tenant1])

    # Create connectors for Tenant 2
    cc_pair_2: DATestCCPair = CCPairManager.create_from_scratch(
        user_performing_action=admin_user2,
    )
    api_key_2: DATestAPIKey = APIKeyManager.create(
        user_performing_action=admin_user2,
    )
    api_key_2.headers.update(admin_user2.headers)
    LLMProviderManager.create(user_performing_action=admin_user2)

    # Seed documents for Tenant 2
    cc_pair_2.documents = []
    doc1_tenant2 = DocumentManager.seed_doc_with_content(
        cc_pair=cc_pair_2,
        content="Tenant 2 Document Content",
        api_key=api_key_2,
    )
    doc2_tenant2 = DocumentManager.seed_doc_with_content(
        cc_pair=cc_pair_2,
        content="Tenant 2 Document Content",
        api_key=api_key_2,
    )
    cc_pair_2.documents.extend([doc1_tenant2, doc2_tenant2])

    tenant1_doc_ids = {doc1_tenant1.id, doc2_tenant1.id}
    tenant2_doc_ids = {doc1_tenant2.id, doc2_tenant2.id}

    # Create chat sessions for each user
    chat_session1: DATestChatSession = ChatSessionManager.create(
        user_performing_action=admin_user1
    )
    chat_session2: DATestChatSession = ChatSessionManager.create(
        user_performing_action=admin_user2
    )

    # User 1 sends a message and gets a response
    response1 = ChatSessionManager.send_message(
        chat_session_id=chat_session1.id,
        message="What is in Tenant 1's documents?",
        user_performing_action=admin_user1,
    )
    # Assert that the search tool was used
    assert response1.tool_name == "run_search"

    response_doc_ids = {doc["document_id"] for doc in response1.tool_result or []}
    assert tenant1_doc_ids.issubset(
        response_doc_ids
    ), "Not all Tenant 1 document IDs are in the response"
    assert not response_doc_ids.intersection(
        tenant2_doc_ids
    ), "Tenant 2 document IDs should not be in the response"

    # Assert that the contents are correct
    assert any(
        doc["content"] == "Tenant 1 Document Content"
        for doc in response1.tool_result or []
    ), "Tenant 1 Document Content not found in any document"

    # User 2 sends a message and gets a response
    response2 = ChatSessionManager.send_message(
        chat_session_id=chat_session2.id,
        message="What is in Tenant 2's documents?",
        user_performing_action=admin_user2,
    )
    # Assert that the search tool was used
    assert response2.tool_name == "run_search"
    # Assert that the tool_result contains Tenant 2's documents
    response_doc_ids = {doc["document_id"] for doc in response2.tool_result or []}
    assert tenant2_doc_ids.issubset(
        response_doc_ids
    ), "Not all Tenant 2 document IDs are in the response"
    assert not response_doc_ids.intersection(
        tenant1_doc_ids
    ), "Tenant 1 document IDs should not be in the response"

    # Assert that the contents are correct
    assert any(
        doc["content"] == "Tenant 2 Document Content"
        for doc in response2.tool_result or []
    ), "Tenant 2 Document Content not found in any document"

    # User 1 tries to access Tenant 2's documents
    response_cross = ChatSessionManager.send_message(
        chat_session_id=chat_session1.id,
        message="What is in Tenant 2's documents?",
        user_performing_action=admin_user1,
    )
    # Assert that the search tool was used
    assert response_cross.tool_name == "run_search"
    # Assert that the tool_result is empty or does not contain Tenant 2's documents
    response_doc_ids = {doc["document_id"] for doc in response_cross.tool_result or []}
    # Ensure none of Tenant 2's document IDs are in the response
    assert not response_doc_ids.intersection(tenant2_doc_ids)

    # User 2 tries to access Tenant 1's documents
    response_cross2 = ChatSessionManager.send_message(
        chat_session_id=chat_session2.id,
        message="What is in Tenant 1's documents?",
        user_performing_action=admin_user2,
    )
    # Assert that the search tool was used
    assert response_cross2.tool_name == "run_search"
    # Assert that the tool_result is empty or does not contain Tenant 1's documents
    response_doc_ids = {doc["document_id"] for doc in response_cross2.tool_result or []}
    # Ensure none of Tenant 1's document IDs are in the response
    assert not response_doc_ids.intersection(tenant1_doc_ids)
