import json

import requests

from onyx.configs.constants import MessageType
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.constants import NUM_DOCS
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestAPIKey
from tests.integration.common_utils.test_models import DATestCCPair
from tests.integration.common_utils.test_models import DATestUser


def test_send_message_simple_with_history(reset: None) -> None:
    # Creating an admin user (first user created is automatically an admin)
    admin_user: DATestUser = UserManager.create(name="admin_user")

    # create connectors
    cc_pair_1: DATestCCPair = CCPairManager.create_from_scratch(
        user_performing_action=admin_user,
    )
    api_key: DATestAPIKey = APIKeyManager.create(
        user_performing_action=admin_user,
    )
    LLMProviderManager.create(user_performing_action=admin_user)
    cc_pair_1.documents = DocumentManager.seed_dummy_docs(
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
    assert response_json["top_documents"][0]["document_id"] == cc_pair_1.documents[0].id

    # assert that the metadata is correct
    for doc in cc_pair_1.documents:
        found_doc = next(
            (x for x in response_json["simple_search_docs"] if x["id"] == doc.id), None
        )
        assert found_doc
        assert found_doc["metadata"]["document_id"] == doc.id


def test_using_reference_docs_with_simple_with_history_api_flow(reset: None) -> None:
    # Creating an admin user (first user created is automatically an admin)
    admin_user: DATestUser = UserManager.create(name="admin_user")

    # create connector
    cc_pair_1: DATestCCPair = CCPairManager.create_from_scratch(
        user_performing_action=admin_user,
    )
    api_key: DATestAPIKey = APIKeyManager.create(
        user_performing_action=admin_user,
    )
    LLMProviderManager.create(user_performing_action=admin_user)

    # SEEDING DOCUMENTS
    cc_pair_1.documents = []
    cc_pair_1.documents.append(
        DocumentManager.seed_doc_with_content(
            cc_pair=cc_pair_1,
            content="Chris's favorite color is blue",
            api_key=api_key,
        )
    )
    cc_pair_1.documents.append(
        DocumentManager.seed_doc_with_content(
            cc_pair=cc_pair_1,
            content="Hagen's favorite color is red",
            api_key=api_key,
        )
    )
    cc_pair_1.documents.append(
        DocumentManager.seed_doc_with_content(
            cc_pair=cc_pair_1,
            content="Pablo's favorite color is green",
            api_key=api_key,
        )
    )

    # SEINDING MESSAGE 1
    response = requests.post(
        f"{API_SERVER_URL}/chat/send-message-simple-with-history",
        json={
            "messages": [
                {
                    "message": "What is Pablo's favorite color?",
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

    # get the db_doc_id of the top document to use as a search doc id for second message
    first_db_doc_id = response_json["top_documents"][0]["db_doc_id"]

    # SEINDING MESSAGE 2
    response = requests.post(
        f"{API_SERVER_URL}/chat/send-message-simple-with-history",
        json={
            "messages": [
                {
                    "message": "What is Pablo's favorite color?",
                    "role": MessageType.USER.value,
                }
            ],
            "persona_id": 0,
            "prompt_id": 0,
            "search_doc_ids": [first_db_doc_id],
        },
        headers=admin_user.headers,
    )
    assert response.status_code == 200
    response_json = response.json()

    # make sure there is an answer
    assert response_json["answer"]

    # since we only gave it one search doc, all responses should only contain that doc
    assert response_json["final_context_doc_indices"] == [0]
    assert response_json["llm_selected_doc_indices"] == [0]
    assert cc_pair_1.documents[2].id in response_json["cited_documents"].values()
    # This ensures the the document we think we are referencing when we send the search_doc_ids in the second
    # message is the document that we expect it to be
    assert response_json["top_documents"][0]["document_id"] == cc_pair_1.documents[2].id


def test_send_message_simple_with_history_strict_json(
    new_admin_user: DATestUser | None,
) -> None:
    # create connectors
    LLMProviderManager.create(user_performing_action=new_admin_user)

    response = requests.post(
        f"{API_SERVER_URL}/chat/send-message-simple-with-history",
        json={
            # intentionally not relevant prompt to ensure that the
            # structured response format is actually used
            "messages": [
                {
                    "message": "What is green?",
                    "role": MessageType.USER.value,
                }
            ],
            "persona_id": 0,
            "prompt_id": 0,
            "structured_response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "presidents",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "presidents": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of the first three US presidents",
                            }
                        },
                        "required": ["presidents"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            },
        },
        headers=new_admin_user.headers if new_admin_user else GENERAL_HEADERS,
    )
    assert response.status_code == 200

    response_json = response.json()

    # Check that the answer is present
    assert "answer" in response_json
    assert response_json["answer"] is not None

    # helper
    def clean_json_string(json_string: str) -> str:
        return json_string.strip().removeprefix("```json").removesuffix("```").strip()

    # Attempt to parse the answer as JSON
    try:
        clean_answer = clean_json_string(response_json["answer"])
        parsed_answer = json.loads(clean_answer)

        # NOTE: do not check content, just the structure
        assert isinstance(parsed_answer, dict)
        assert "presidents" in parsed_answer
        assert isinstance(parsed_answer["presidents"], list)
        for president in parsed_answer["presidents"]:
            assert isinstance(president, str)
    except json.JSONDecodeError:
        assert (
            False
        ), f"The answer is not a valid JSON object - '{response_json['answer']}'"

    # Check that the answer_citationless is also valid JSON
    assert "answer_citationless" in response_json
    assert response_json["answer_citationless"] is not None
    try:
        clean_answer_citationless = clean_json_string(
            response_json["answer_citationless"]
        )
        parsed_answer_citationless = json.loads(clean_answer_citationless)
        assert isinstance(parsed_answer_citationless, dict)
    except json.JSONDecodeError:
        assert False, "The answer_citationless is not a valid JSON object"
