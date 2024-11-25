from uuid import UUID

import pytest
import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser

BASE_URL = f"{API_SERVER_URL}/openai-assistants"


@pytest.fixture
def run_id(admin_user: DATestUser | None, thread_id: UUID) -> str:
    """Create a run and return its ID."""
    response = requests.post(
        f"{BASE_URL}/threads/{thread_id}/runs",
        json={
            "assistant_id": 0,
        },
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert response.status_code == 200
    return response.json()["id"]


def test_create_run(
    admin_user: DATestUser | None, thread_id: UUID, llm_provider: DATestLLMProvider
) -> None:
    response = requests.post(
        f"{BASE_URL}/threads/{thread_id}/runs",
        json={
            "assistant_id": 0,
            "model": "gpt-3.5-turbo",
            "instructions": "Test instructions",
        },
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert response.status_code == 200

    response_json = response.json()
    assert "id" in response_json
    assert response_json["object"] == "thread.run"
    assert "created_at" in response_json
    assert response_json["assistant_id"] == 0
    assert UUID(response_json["thread_id"]) == thread_id
    assert response_json["status"] == "queued"
    assert response_json["model"] == "gpt-3.5-turbo"
    assert response_json["instructions"] == "Test instructions"


def test_retrieve_run(
    admin_user: DATestUser | None,
    thread_id: UUID,
    run_id: str,
    llm_provider: DATestLLMProvider,
) -> None:
    retrieve_response = requests.get(
        f"{BASE_URL}/threads/{thread_id}/runs/{run_id}",
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert retrieve_response.status_code == 200

    response_json = retrieve_response.json()
    assert response_json["id"] == run_id
    assert response_json["object"] == "thread.run"
    assert "created_at" in response_json
    assert UUID(response_json["thread_id"]) == thread_id


def test_cancel_run(
    admin_user: DATestUser | None,
    thread_id: UUID,
    run_id: str,
    llm_provider: DATestLLMProvider,
) -> None:
    cancel_response = requests.post(
        f"{BASE_URL}/threads/{thread_id}/runs/{run_id}/cancel",
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert cancel_response.status_code == 200

    response_json = cancel_response.json()
    assert response_json["id"] == run_id
    assert response_json["status"] == "cancelled"


def test_list_runs(
    admin_user: DATestUser | None, thread_id: UUID, llm_provider: DATestLLMProvider
) -> None:
    # Create a few runs
    for _ in range(3):
        requests.post(
            f"{BASE_URL}/threads/{thread_id}/runs",
            json={
                "assistant_id": 0,
            },
            headers=admin_user.headers if admin_user else GENERAL_HEADERS,
        )

    # Now, list the runs
    list_response = requests.get(
        f"{BASE_URL}/threads/{thread_id}/runs",
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert list_response.status_code == 200

    response_json = list_response.json()
    assert isinstance(response_json, list)
    assert len(response_json) >= 3

    for run in response_json:
        assert "id" in run
        assert run["object"] == "thread.run"
        assert "created_at" in run
        assert UUID(run["thread_id"]) == thread_id
        assert "status" in run
        assert "model" in run


def test_list_run_steps(
    admin_user: DATestUser | None,
    thread_id: UUID,
    run_id: str,
    llm_provider: DATestLLMProvider,
) -> None:
    steps_response = requests.get(
        f"{BASE_URL}/threads/{thread_id}/runs/{run_id}/steps",
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert steps_response.status_code == 200

    response_json = steps_response.json()
    assert isinstance(response_json, list)
    # Since DAnswer doesn't have an equivalent to run steps, we expect an empty list
    assert len(response_json) == 0
