import json
import os

import pytest
import requests

from onyx.configs.constants import MessageType
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import NUM_DOCS
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.conftest import DocumentBuilderType


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="/chat/send-message-simple-with-history tests are enterprise only",
)
def test_send_message_simple_with_history(
    reset: None,
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
    document_builder: DocumentBuilderType,
) -> None:
    # create documents using the document builder
    # Create NUM_DOCS number of documents with dummy content
    content_list = [f"Document {i} content" for i in range(NUM_DOCS)]
    docs = document_builder(content_list)

    response = requests.post(
        f"{API_SERVER_URL}/chat/send-message-simple-with-history",
        json={
            "messages": [
                {
                    "message": docs[0].content,
                    "role": MessageType.USER.value,
                }
            ],
            "persona_id": 0,
        },
        headers=admin_user.headers,
    )
    assert response.status_code == 200

    response_json = response.json()

    # Check that the top document is the correct document
    assert response_json["top_documents"][0]["document_id"] == docs[0].id

    # assert that the metadata is correct
    for doc in docs:
        found_doc = next(
            (x for x in response_json["top_documents"] if x["document_id"] == doc.id),
            None,
        )
        assert found_doc
        assert found_doc["metadata"]["document_id"] == doc.id


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="/chat/send-message-simple-with-history tests are enterprise only",
)
def test_using_reference_docs_with_simple_with_history_api_flow(
    reset: None,
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
    document_builder: DocumentBuilderType,
) -> None:
    # SEEDING DOCUMENTS
    docs = document_builder(
        [
            "Chris's favorite color is blue",
            "Hagen's favorite color is red",
            "Pablo's favorite color is green",
        ]
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
            "search_doc_ids": [first_db_doc_id],
        },
        headers=admin_user.headers,
    )
    assert response.status_code == 200
    response_json = response.json()

    # make sure there is an answer
    assert response_json["answer"]

    # This ensures the the document we think we are referencing when we send the search_doc_ids in the second
    # message is the document that we expect it to be
    assert response_json["top_documents"][0]["document_id"] == docs[2].id


@pytest.mark.skip(reason="We don't support this anymore with the DR flow :(")
@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="/chat/send-message-simple-with-history tests are enterprise only",
)
def test_send_message_simple_with_history_strict_json(
    reset: None,
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
) -> None:

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
        headers=admin_user.headers,
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


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="/query/answer-with-citation tests are enterprise only",
)
def test_answer_with_citation_api(
    reset: None,
    admin_user: DATestUser,
    llm_provider: DATestLLMProvider,
    document_builder: DocumentBuilderType,
) -> None:

    # create docs
    docs = document_builder(["Chris' favorite color is green"])

    # send a message
    response = requests.post(
        f"{API_SERVER_URL}/query/answer-with-citation",
        json={
            "messages": [
                {
                    "message": "What is Chris' favorite color? Make sure to cite the document.",
                    "role": MessageType.USER.value,
                }
            ],
            "persona_id": 0,
        },
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["answer"]

    has_correct_citation = False
    for citation in response_json["citations"]:
        if citation["document_id"] == docs[0].id:
            has_correct_citation = True
            break

    assert has_correct_citation
