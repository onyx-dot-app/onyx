from uuid import UUID

import requests

from onyx.db.models import ChatSessionSharedStatus
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import DATestUser

THREADS_URL = f"{API_SERVER_URL}/openai-assistants/threads"


def test_create_thread(admin_user: DATestUser | None) -> None:
    response = requests.post(
        THREADS_URL,
        json={"messages": None, "metadata": {"key": "value"}},
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert response.status_code == 200

    response_json = response.json()
    assert "id" in response_json
    assert response_json["object"] == "thread"
    assert "created_at" in response_json
    assert response_json["metadata"] == {"key": "value"}


def test_retrieve_thread(admin_user: DATestUser | None) -> None:
    # First, create a thread
    create_response = requests.post(
        THREADS_URL,
        json={},
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert create_response.status_code == 200
    thread_id = create_response.json()["id"]

    # Now, retrieve the thread
    retrieve_response = requests.get(
        f"{THREADS_URL}/{thread_id}",
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert retrieve_response.status_code == 200

    response_json = retrieve_response.json()
    assert response_json["id"] == thread_id
    assert response_json["object"] == "thread"
    assert "created_at" in response_json


def test_modify_thread(admin_user: DATestUser | None) -> None:
    # First, create a thread
    create_response = requests.post(
        THREADS_URL,
        json={},
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert create_response.status_code == 200
    thread_id = create_response.json()["id"]

    # Now, modify the thread
    modify_response = requests.post(
        f"{THREADS_URL}/{thread_id}",
        json={"metadata": {"new_key": "new_value"}},
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert modify_response.status_code == 200

    response_json = modify_response.json()
    assert response_json["id"] == thread_id
    assert response_json["metadata"] == {"new_key": "new_value"}


def test_delete_thread(admin_user: DATestUser | None) -> None:
    # First, create a thread
    create_response = requests.post(
        THREADS_URL,
        json={},
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert create_response.status_code == 200
    thread_id = create_response.json()["id"]

    # Now, delete the thread
    delete_response = requests.delete(
        f"{THREADS_URL}/{thread_id}",
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert delete_response.status_code == 200

    response_json = delete_response.json()
    assert response_json["id"] == thread_id
    assert response_json["object"] == "thread.deleted"
    assert response_json["deleted"] is True


def test_list_threads(admin_user: DATestUser | None) -> None:
    # Create a few threads
    for _ in range(3):
        requests.post(
            THREADS_URL,
            json={},
            headers=admin_user.headers if admin_user else GENERAL_HEADERS,
        )

    # Now, list the threads
    list_response = requests.get(
        THREADS_URL,
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert list_response.status_code == 200

    response_json = list_response.json()
    assert "sessions" in response_json
    assert len(response_json["sessions"]) >= 3

    for session in response_json["sessions"]:
        assert "id" in session
        assert "name" in session
        assert "persona_id" in session
        assert "time_created" in session
        assert "shared_status" in session
        assert "current_alternate_model" in session

        # Validate UUID
        UUID(session["id"])

        # Validate shared_status
        assert session["shared_status"] in [
            status.value for status in ChatSessionSharedStatus
        ]
