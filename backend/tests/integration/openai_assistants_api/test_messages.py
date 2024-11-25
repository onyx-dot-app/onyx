import uuid
from typing import Optional

import pytest
import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import DATestUser

BASE_URL = f"{API_SERVER_URL}/openai-assistants/threads"


@pytest.fixture
def thread_id(admin_user: Optional[DATestUser]) -> str:
    response = requests.post(
        BASE_URL,
        json={},
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert response.status_code == 200
    return response.json()["id"]


def test_create_message(admin_user: Optional[DATestUser], thread_id: str) -> None:
    response = requests.post(
        f"{BASE_URL}/{thread_id}/messages",  # URL structure matches API
        json={
            "role": "user",
            "content": "Hello, world!",
            "file_ids": [],
            "metadata": {"key": "value"},
        },
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert response.status_code == 200

    response_json = response.json()
    assert "id" in response_json
    assert response_json["thread_id"] == thread_id
    assert response_json["role"] == "user"
    assert response_json["content"] == [{"type": "text", "text": "Hello, world!"}]
    assert response_json["metadata"] == {"key": "value"}


def test_list_messages(admin_user: Optional[DATestUser], thread_id: str) -> None:
    # Create a message first
    requests.post(
        f"{BASE_URL}/{thread_id}/messages",
        json={"role": "user", "content": "Test message"},
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )

    # Now, list the messages
    response = requests.get(
        f"{BASE_URL}/{thread_id}/messages",
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert response.status_code == 200

    response_json = response.json()
    assert response_json["object"] == "list"
    assert isinstance(response_json["data"], list)
    assert len(response_json["data"]) > 0
    assert "first_id" in response_json
    assert "last_id" in response_json
    assert "has_more" in response_json


def test_retrieve_message(admin_user: Optional[DATestUser], thread_id: str) -> None:
    # Create a message first
    create_response = requests.post(
        f"{BASE_URL}/{thread_id}/messages",
        json={"role": "user", "content": "Test message"},
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    message_id = create_response.json()["id"]

    # Now, retrieve the message
    response = requests.get(
        f"{BASE_URL}/{thread_id}/messages/{message_id}",
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert response.status_code == 200

    response_json = response.json()
    assert response_json["id"] == message_id
    assert response_json["thread_id"] == thread_id
    assert response_json["role"] == "user"
    assert response_json["content"] == [{"type": "text", "text": "Test message"}]


def test_modify_message(admin_user: Optional[DATestUser], thread_id: str) -> None:
    # Create a message first
    create_response = requests.post(
        f"{BASE_URL}/{thread_id}/messages",
        json={"role": "user", "content": "Test message"},
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    message_id = create_response.json()["id"]

    # Now, modify the message
    response = requests.post(
        f"{BASE_URL}/{thread_id}/messages/{message_id}",
        json={"metadata": {"new_key": "new_value"}},
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert response.status_code == 200

    response_json = response.json()
    assert response_json["id"] == message_id
    assert response_json["thread_id"] == thread_id
    assert response_json["metadata"] == {"new_key": "new_value"}


def test_error_handling(admin_user: Optional[DATestUser]) -> None:
    non_existent_thread_id = str(uuid.uuid4())
    non_existent_message_id = -99

    # Test with non-existent thread
    response = requests.post(
        f"{BASE_URL}/{non_existent_thread_id}/messages",
        json={"role": "user", "content": "Test message"},
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert response.status_code == 404

    # Test with non-existent message
    response = requests.get(
        f"{BASE_URL}/{non_existent_thread_id}/messages/{non_existent_message_id}",
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert response.status_code == 404
