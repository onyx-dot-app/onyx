import requests

from danswer.configs.constants import MessageType
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import NUM_DOCS
from tests.integration.common_utils.llm import LLMProviderManager
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import TestAPIKey
from tests.integration.common_utils.test_models import TestCCPair
from tests.integration.common_utils.test_models import TestUser


def test_send_message_simple_with_history(reset: None) -> None:
    # Creating an admin user (first user created is automatically an admin)
    admin_user: TestUser = UserManager.create(name="admin_user")

    # create connectors
    cc_pair_1: TestCCPair = CCPairManager.create_from_scratch(
        user_performing_action=admin_user,
    )
    api_key: TestAPIKey = APIKeyManager.create(
        user_performing_action=admin_user,
    )
    LLMProviderManager.create(user_performing_action=admin_user)
    cc_pair_1 = DocumentManager.seed_and_attach_docs(
        cc_pair=cc_pair_1,
        num_docs=NUM_DOCS,
        api_key=api_key,
    )

    response = requests.post(
        f"{API_SERVER_URL}/chat/send-message-simple-with-history",
        json={
            "messages": [
                {
                    "message": cc_pair_1.documents[0].content,
                    "role": MessageType.USER.value,
                }
            ],
            "persona_id": 0,
            "prompt_id": 0,
        },
        headers=admin_user.headers,
    )
    assert response.status_code == 200

    response_json = response.json()

    # Check that the top document is the correct document
    assert response_json["simple_search_docs"][0]["id"] == cc_pair_1.documents[0].id

    # assert that the metadata is correct
    for doc in cc_pair_1.documents:
        found_doc = next(
            (x for x in response_json["simple_search_docs"] if x["id"] == doc.id), None
        )
        assert found_doc
        assert found_doc["metadata"]["document_id"] == doc.id
