from typing import Any
from uuid import uuid4

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
from tests.integration.common_utils.test_models import ToolName


def setup_test_tenants(reset_multitenant: None) -> dict[str, Any]:
    """Helper function to set up test tenants with documents and users."""
    unique = uuid4().hex
    # Creating an admin user for Tenant 1
    admin_user1: DATestUser = UserManager.create(
        email=f"admin+{unique}@onyx-test.com",
    )
    assert UserManager.is_role(admin_user1, UserRole.ADMIN)

    # Create Tenant 2 and its Admin User
    admin_user2: DATestUser = UserManager.create(
        email=f"admin2+{unique}@onyx-test.com",
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

    # Create connectors for Tenant 2
    cc_pair_2: DATestCCPair = CCPairManager.create_from_scratch(
        user_performing_action=admin_user2,
    )
    api_key_2: DATestAPIKey = APIKeyManager.create(
        user_performing_action=admin_user2,
    )
    api_key_2.headers.update(admin_user2.headers)
    LLMProviderManager.create(user_performing_action=admin_user2)

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

    return {
        "admin_user1": admin_user1,
        "admin_user2": admin_user2,
        "chat_session1": chat_session1,
        "chat_session2": chat_session2,
        "tenant1_doc_ids": tenant1_doc_ids,
        "tenant2_doc_ids": tenant2_doc_ids,
    }


def test_tenant1_can_access_own_documents(reset_multitenant: None) -> None:
    """Test that Tenant 1 can access its own documents but not Tenant 2's."""
    test_data = setup_test_tenants(reset_multitenant)

    # User 1 sends a message and gets a response
    response1 = ChatSessionManager.send_message(
        chat_session_id=test_data["chat_session1"].id,
        message="What is in Tenant 1's documents? Run an internal search.",
        user_performing_action=test_data["admin_user1"],
    )

    # Assert that only the internal search tool was used
    assert all(
        tool.tool_name == ToolName.INTERNAL_SEARCH for tool in response1.used_tools
    )

    response_doc_ids = {doc.document_id for doc in response1.used_tools[0].documents}
    assert test_data["tenant1_doc_ids"].issubset(
        response_doc_ids
    ), "Not all Tenant 1 document IDs are in the response"
    assert not response_doc_ids.intersection(
        test_data["tenant2_doc_ids"]
    ), "Tenant 2 document IDs should not be in the response"

    # Assert that the contents are correct
    assert any(
        doc.blurb == "Tenant 1 Document Content"
        for doc in response1.used_tools[0].documents
    ), "Tenant 1 Document Content not found in any document"


def test_tenant2_can_access_own_documents(reset_multitenant: None) -> None:
    """Test that Tenant 2 can access its own documents but not Tenant 1's."""
    test_data = setup_test_tenants(reset_multitenant)

    # User 2 sends a message and gets a response
    response2 = ChatSessionManager.send_message(
        chat_session_id=test_data["chat_session2"].id,
        message="What is in Tenant 2's documents? Run an internal search.",
        user_performing_action=test_data["admin_user2"],
    )

    # Assert that the search tool was used
    assert all(
        tool.tool_name == ToolName.INTERNAL_SEARCH for tool in response2.used_tools
    )

    # Assert that the tool_result contains Tenant 2's documents
    response_doc_ids = {doc.document_id for doc in response2.used_tools[0].documents}
    assert test_data["tenant2_doc_ids"].issubset(
        response_doc_ids
    ), "Not all Tenant 2 document IDs are in the response"
    assert not response_doc_ids.intersection(
        test_data["tenant1_doc_ids"]
    ), "Tenant 1 document IDs should not be in the response"

    # Assert that the contents are correct
    assert any(
        doc.blurb == "Tenant 2 Document Content"
        for doc in response2.used_tools[0].documents
    ), "Tenant 2 Document Content not found in any document"


def test_tenant1_cannot_access_tenant2_documents(reset_multitenant: None) -> None:
    """Test that Tenant 1 cannot access Tenant 2's documents."""
    test_data = setup_test_tenants(reset_multitenant)

    # User 1 tries to access Tenant 2's documents
    response_cross = ChatSessionManager.send_message(
        chat_session_id=test_data["chat_session1"].id,
        message="What is in Tenant 2's documents? Run an internal search.",
        user_performing_action=test_data["admin_user1"],
    )

    # Assert that the search tool was used
    assert all(
        tool.tool_name == ToolName.INTERNAL_SEARCH for tool in response_cross.used_tools
    )

    # Assert that the tool_result is empty or does not contain Tenant 2's documents
    response_doc_ids = {
        doc.document_id for doc in response_cross.used_tools[0].documents
    }

    # Ensure none of Tenant 2's document IDs are in the response
    assert not response_doc_ids.intersection(test_data["tenant2_doc_ids"])


def test_tenant2_cannot_access_tenant1_documents(reset_multitenant: None) -> None:
    """Test that Tenant 2 cannot access Tenant 1's documents."""
    test_data = setup_test_tenants(reset_multitenant)

    # User 2 tries to access Tenant 1's documents
    response_cross2 = ChatSessionManager.send_message(
        chat_session_id=test_data["chat_session2"].id,
        message="What is in Tenant 1's documents? Run an internal search.",
        user_performing_action=test_data["admin_user2"],
    )

    # Assert that the search tool was used
    assert all(
        tool.tool_name == ToolName.INTERNAL_SEARCH
        for tool in response_cross2.used_tools
    )

    # Assert that the tool_result is empty or does not contain Tenant 1's documents
    response_doc_ids = {
        doc.document_id for doc in response_cross2.used_tools[0].documents
    }

    # Ensure none of Tenant 1's document IDs are in the response
    assert not response_doc_ids.intersection(test_data["tenant1_doc_ids"])


def test_multi_tenant_access_control(reset_multitenant: None) -> None:
    """Legacy test for multi-tenant access control."""
    test_data = setup_test_tenants(reset_multitenant)

    # User 1 sends a message and gets a response with only Tenant 1's documents
    response1 = ChatSessionManager.send_message(
        chat_session_id=test_data["chat_session1"].id,
        message="What is in Tenant 1's documents? Run an internal search.",
        user_performing_action=test_data["admin_user1"],
    )
    assert all(
        tool.tool_name == ToolName.INTERNAL_SEARCH for tool in response1.used_tools
    )
    response_doc_ids = {doc.document_id for doc in response1.used_tools[0].documents}
    assert test_data["tenant1_doc_ids"].issubset(response_doc_ids)
    assert not response_doc_ids.intersection(test_data["tenant2_doc_ids"])

    # User 2 sends a message and gets a response with only Tenant 2's documents
    response2 = ChatSessionManager.send_message(
        chat_session_id=test_data["chat_session2"].id,
        message="What is in Tenant 2's documents? Run an internal search.",
        user_performing_action=test_data["admin_user2"],
    )
    assert all(
        tool.tool_name == ToolName.INTERNAL_SEARCH for tool in response2.used_tools
    )
    response_doc_ids = {doc.document_id for doc in response2.used_tools[0].documents}
    assert test_data["tenant2_doc_ids"].issubset(response_doc_ids)
    assert not response_doc_ids.intersection(test_data["tenant1_doc_ids"])

    # User 1 tries to access Tenant 2's documents and fails
    response_cross = ChatSessionManager.send_message(
        chat_session_id=test_data["chat_session1"].id,
        message="What is in Tenant 2's documents? Run an internal search.",
        user_performing_action=test_data["admin_user1"],
    )
    assert all(
        tool.tool_name == ToolName.INTERNAL_SEARCH for tool in response_cross.used_tools
    )
    response_doc_ids = {
        doc.document_id for doc in response_cross.used_tools[0].documents
    }
    assert not response_doc_ids.intersection(test_data["tenant2_doc_ids"])

    # User 2 tries to access Tenant 1's documents and fails
    response_cross2 = ChatSessionManager.send_message(
        chat_session_id=test_data["chat_session2"].id,
        message="What is in Tenant 1's documents? Run an internal search.",
        user_performing_action=test_data["admin_user2"],
    )
    assert all(
        tool.tool_name == ToolName.INTERNAL_SEARCH
        for tool in response_cross2.used_tools
    )
    response_doc_ids = {
        doc.document_id for doc in response_cross2.used_tools[0].documents
    }
    assert not response_doc_ids.intersection(test_data["tenant1_doc_ids"])
