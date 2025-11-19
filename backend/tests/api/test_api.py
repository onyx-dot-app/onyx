import os
from collections.abc import Generator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from onyx.configs.constants import DEV_VERSION_PATTERN
from onyx.configs.constants import STABLE_VERSION_PATTERN
from onyx.main import fetch_versioned_implementation
from onyx.utils.logger import setup_logger

logger = setup_logger()


@pytest.fixture(scope="function")
def client() -> Generator[TestClient, Any, None]:
    # Set environment variables
    os.environ["ENABLE_PAID_ENTERPRISE_EDITION_FEATURES"] = "True"

    # Initialize TestClient with the FastAPI app
    app: FastAPI = fetch_versioned_implementation(
        module="onyx.main", attribute="get_application"
    )()
    client = TestClient(app)
    yield client


@pytest.mark.skip(
    reason="enable when we have a testing environment with preloaded data"
)
def test_handle_simplified_chat_message(client: TestClient) -> None:
    req: dict[str, Any] = {}

    req["persona_id"] = 0
    req["description"] = "pytest"
    response = client.post("/chat/create-chat-session", json=req)
    chat_session_id = response.json()["chat_session_id"]

    req = {}
    req["chat_session_id"] = chat_session_id
    req["message"] = "hello"

    response = client.post("/chat/send-message-simple-api", json=req)
    assert response.status_code == 200


@pytest.mark.skip(
    reason="enable when we have a testing environment with preloaded data"
)
def test_handle_send_message_simple_with_history(client: TestClient) -> None:
    req: dict[str, Any] = {}
    messages = []
    messages.append({"message": "What sorts of questions can you answer for me?"})
    # messages.append({"message":
    #                  "I'd be happy to assist you with a wide range of questions related to Ramp's expense management platform. "
    #                  "I can help with topics such as:\n\n"
    #                  "1. Setting up and managing your Ramp account\n"
    #                  "2. Using Ramp cards and making purchases\n"
    #                  "3. Submitting and reviewing expenses\n"
    #                  "4. Understanding Ramp's features and benefits\n"
    #                  "5. Navigating the Ramp dashboard and mobile app\n"
    #                  "6. Managing team spending and budgets\n"
    #                  "7. Integrating Ramp with accounting software\n"
    #                  "8. Troubleshooting common issues\n\n"
    #                  "Feel free to ask any specific questions you have about using Ramp, "
    #                  "and I'll do my best to provide clear and helpful answers. "
    #                  "Is there a particular area you'd like to know more about?",
    #                  "role": "assistant"})
    # req["prompt_id"] = 9
    # req["persona_id"] = 6

    # Yoda
    req["persona_id"] = 1
    messages.append(
        {
            "message": "Answer questions for you, I can. "
            "About many topics, knowledge I have. "
            "But specific to documents provided, limited my responses are. "
            "Ask you may about:\n\n"
            "- User interviews and building trust with participants\n"
            "- Designing effective surveys and survey questions  \n"
            "- Product analysis approaches\n"
            "- Recruiting participants for research\n"
            "- Discussion guides for user interviews\n"
            "- Types of survey questions\n\n"
            "More there may be, but focus on these areas, the given context does. "
            "Specific questions you have, ask you should. Guide you I will, as best I can.",
            "role": "assistant",
        }
    )
    # messages.append({"message": "Where can I pilot a survey?"})

    # messages.append({"message": "How many data points should I collect to validate my solution?"})
    messages.append({"message": "What is solution validation research used for?"})

    req["messages"] = messages

    response = client.post("/chat/send-message-simple-with-history", json=req)
    assert response.status_code == 200

    resp_json = response.json()

    # persona must have LLM relevance enabled for this to pass
    assert len(resp_json["llm_selected_doc_indices"]) > 0


def test_versions_endpoint(client: TestClient) -> None:
    """Test that /api/versions endpoint returns valid stable, dev, and migration configurations"""
    response = client.get("/versions")
    assert response.status_code == 200

    data = response.json()

    # Verify the top-level structure
    assert "stable" in data
    assert "dev" in data
    assert "migration" in data

    # Verify stable configuration
    stable = data["stable"]
    assert "onyx" in stable
    assert "relational_db" in stable
    assert "index" in stable
    assert "nginx" in stable

    # Verify stable version follows correct pattern (v1.2.3)
    # If this fails, revise latest Github release for typo or incorrect version name
    assert STABLE_VERSION_PATTERN.match(
        stable["onyx"]
    ), f"Stable version {stable['onyx']} doesn't match pattern v(number).(number).(number)"

    # Verify dev configuration
    dev = data["dev"]
    assert "onyx" in dev
    assert "relational_db" in dev
    assert "index" in dev
    assert "nginx" in dev

    # Verify dev version follows correct pattern (v1.2.3-beta.4)
    assert DEV_VERSION_PATTERN.match(
        dev["onyx"]
    ), f"Dev version {dev['onyx']} doesn't match pattern v(number).(number).(number)-beta.(number)"

    # Verify migration configuration
    migration = data["migration"]
    assert "onyx" in migration
    assert "relational_db" in migration
    assert "index" in migration
    assert "nginx" in migration

    # Verify migration has expected values
    assert migration["onyx"] == "airgapped-intfloat-nomic-migration"
    assert migration["relational_db"] == "postgres:15.2-alpine"
    assert migration["index"] == "vespaengine/vespa:8.277.17"
    assert migration["nginx"] == "nginx:1.23.4-alpine"

    # Verify versions are different between stable and dev
    assert stable["onyx"] != dev["onyx"], "Stable and dev versions should be different"

    # Additional validation: ensure all required fields are strings
    for config_name, config in [
        ("stable", stable),
        ("dev", dev),
        ("migration", migration),
    ]:
        for field_name, field_value in config.items():
            assert isinstance(
                field_value, str
            ), f"{config_name}.{field_name} should be a string, got {type(field_value)}"
            assert (
                field_value.strip() != ""
            ), f"{config_name}.{field_name} should not be empty"
