import requests

from tests.integration.common_utils.connectors import ConnectorClient
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.seed_documents import TestDocumentClient


def test_send_message_simple_with_history(reset: None) -> None:
    # create connectors
    c1_details = ConnectorClient.create_connector(name_prefix="tc1")
    c1_seed_res = TestDocumentClient.seed_documents(
        num_docs=5, cc_pair_id=c1_details.cc_pair_id
    )

    response = requests.post(
        f"{API_SERVER_URL}/chat/send-message-simple-with-history",
        json={
            "messages": [{"message": c1_seed_res.documents[0].content, "role": "user"}],
            "persona_id": 0,
            "prompt_id": 0,
        },
    )
    assert response.status_code == 200

    response_json = response.json()

    # Check that the top document is the correct document
    assert response_json["simple_search_docs"][0]["id"] == c1_seed_res.documents[0].id

    # assert that the metadata is correct
    for doc in c1_seed_res.documents:
        found_doc = next(
            (x for x in response_json["simple_search_docs"] if x["id"] == doc.id), None
        )
        assert found_doc
        assert found_doc["metadata"]["document_id"] == doc.id
