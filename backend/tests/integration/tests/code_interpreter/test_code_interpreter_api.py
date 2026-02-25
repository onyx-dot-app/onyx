import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.tool import ToolManager
from tests.integration.common_utils.test_models import DATestUser

CODE_INTERPRETER_URL = f"{API_SERVER_URL}/admin/code-interpreter"
CODE_INTERPRETER_HEALTH_URL = f"{CODE_INTERPRETER_URL}/health"
PYTHON_TOOL_NAME = "python"


def test_get_code_interpreter_health_as_admin(
    admin_user: DATestUser,
) -> None:
    """Health endpoint should return a JSON object with a 'healthy' boolean."""
    response = requests.get(
        CODE_INTERPRETER_HEALTH_URL,
        headers=admin_user.headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "healthy" in data
    assert isinstance(data["healthy"], bool)


def test_get_code_interpreter_status_as_admin(
    admin_user: DATestUser,
) -> None:
    """GET endpoint should return a JSON object with an 'enabled' boolean."""
    response = requests.get(
        CODE_INTERPRETER_URL,
        headers=admin_user.headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "enabled" in data
    assert isinstance(data["enabled"], bool)


def test_update_code_interpreter_disable_and_enable(
    admin_user: DATestUser,
) -> None:
    """PUT endpoint should update the enabled flag and persist across reads."""
    # Disable
    response = requests.put(
        CODE_INTERPRETER_URL,
        json={"enabled": False},
        headers=admin_user.headers,
    )
    assert response.status_code == 200

    # Verify disabled
    response = requests.get(
        CODE_INTERPRETER_URL,
        headers=admin_user.headers,
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False

    # Re-enable
    response = requests.put(
        CODE_INTERPRETER_URL,
        json={"enabled": True},
        headers=admin_user.headers,
    )
    assert response.status_code == 200

    # Verify enabled
    response = requests.get(
        CODE_INTERPRETER_URL,
        headers=admin_user.headers,
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is True


def test_code_interpreter_endpoints_require_admin(
    basic_user: DATestUser,
) -> None:
    """All code interpreter endpoints should reject non-admin users."""
    health_response = requests.get(
        CODE_INTERPRETER_HEALTH_URL,
        headers=basic_user.headers,
    )
    assert health_response.status_code == 403

    get_response = requests.get(
        CODE_INTERPRETER_URL,
        headers=basic_user.headers,
    )
    assert get_response.status_code == 403

    put_response = requests.put(
        CODE_INTERPRETER_URL,
        json={"enabled": True},
        headers=basic_user.headers,
    )
    assert put_response.status_code == 403


def test_python_tool_hidden_from_tool_list_when_disabled(
    admin_user: DATestUser,
) -> None:
    """When code interpreter is disabled, the Python tool should not appear
    in the GET /tool response (i.e. the frontend tool list)."""
    # Disable
    response = requests.put(
        CODE_INTERPRETER_URL,
        json={"enabled": False},
        headers=admin_user.headers,
    )
    assert response.status_code == 200

    # Python tool should not be in the tool list
    tools = ToolManager.list_tools(user_performing_action=admin_user)
    tool_names = [t.name for t in tools]
    assert PYTHON_TOOL_NAME not in tool_names

    # Re-enable
    response = requests.put(
        CODE_INTERPRETER_URL,
        json={"enabled": True},
        headers=admin_user.headers,
    )
    assert response.status_code == 200

    # Python tool should reappear
    tools = ToolManager.list_tools(user_performing_action=admin_user)
    tool_names = [t.name for t in tools]
    assert PYTHON_TOOL_NAME in tool_names
