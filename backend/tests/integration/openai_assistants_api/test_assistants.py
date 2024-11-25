import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import DATestUser

ASSISTANTS_URL = f"{API_SERVER_URL}/openai-assistants/assistants"


def test_create_assistant(admin_user: DATestUser | None) -> None:
    response = requests.post(
        ASSISTANTS_URL,
        json={
            "model": "gpt-3.5-turbo",
            "name": "Test Assistant",
            "description": "A test assistant",
            "instructions": "You are a helpful assistant.",
        },
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Assistant"
    assert data["description"] == "A test assistant"
    assert data["model"] == "gpt-3.5-turbo"
    assert data["instructions"] == "You are a helpful assistant."


def test_retrieve_assistant(admin_user: DATestUser | None) -> None:
    # First, create an assistant
    create_response = requests.post(
        ASSISTANTS_URL,
        json={"model": "gpt-3.5-turbo", "name": "Retrieve Test"},
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert create_response.status_code == 200
    assistant_id = create_response.json()["id"]

    # Now, retrieve the assistant
    response = requests.get(
        f"{ASSISTANTS_URL}/{assistant_id}",
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == assistant_id
    assert data["name"] == "Retrieve Test"


def test_modify_assistant(admin_user: DATestUser | None) -> None:
    # First, create an assistant
    create_response = requests.post(
        ASSISTANTS_URL,
        json={"model": "gpt-3.5-turbo", "name": "Modify Test"},
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert create_response.status_code == 200
    assistant_id = create_response.json()["id"]

    # Now, modify the assistant
    response = requests.post(
        f"{ASSISTANTS_URL}/{assistant_id}",
        json={"name": "Modified Assistant", "instructions": "New instructions"},
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == assistant_id
    assert data["name"] == "Modified Assistant"
    assert data["instructions"] == "New instructions"


def test_delete_assistant(admin_user: DATestUser | None) -> None:
    # First, create an assistant
    create_response = requests.post(
        ASSISTANTS_URL,
        json={"model": "gpt-3.5-turbo", "name": "Delete Test"},
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert create_response.status_code == 200
    assistant_id = create_response.json()["id"]

    # Now, delete the assistant
    response = requests.delete(
        f"{ASSISTANTS_URL}/{assistant_id}",
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == assistant_id
    assert data["deleted"] is True


def test_list_assistants(admin_user: DATestUser | None) -> None:
    # Create multiple assistants
    for i in range(3):
        requests.post(
            ASSISTANTS_URL,
            json={"model": "gpt-3.5-turbo", "name": f"List Test {i}"},
            headers=admin_user.headers if admin_user else GENERAL_HEADERS,
        )

    # Now, list the assistants
    response = requests.get(
        ASSISTANTS_URL,
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "list"
    assert len(data["data"]) >= 3  # At least the 3 we just created
    assert all(assistant["object"] == "assistant" for assistant in data["data"])


def test_list_assistants_pagination(admin_user: DATestUser | None) -> None:
    # Create 5 assistants
    for i in range(5):
        requests.post(
            ASSISTANTS_URL,
            json={"model": "gpt-3.5-turbo", "name": f"Pagination Test {i}"},
            headers=admin_user.headers if admin_user else GENERAL_HEADERS,
        )

    # List assistants with limit
    response = requests.get(
        f"{ASSISTANTS_URL}?limit=2",
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 2
    assert data["has_more"] is True

    # Get next page
    before = data["last_id"]
    response = requests.get(
        f"{ASSISTANTS_URL}?limit=2&before={before}",
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 2


def test_assistant_not_found(admin_user: DATestUser | None) -> None:
    non_existent_id = -99
    response = requests.get(
        f"{ASSISTANTS_URL}/{non_existent_id}",
        headers=admin_user.headers if admin_user else GENERAL_HEADERS,
    )
    assert response.status_code == 404
