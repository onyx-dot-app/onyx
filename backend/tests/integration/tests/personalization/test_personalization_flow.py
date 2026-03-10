import requests

from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


def _get_auth_headers(user: DATestUser) -> tuple[dict, dict]:
    return user.headers, {
        FASTAPI_USERS_AUTH_COOKIE_NAME: user.cookies[FASTAPI_USERS_AUTH_COOKIE_NAME]
    }


def _get_me(headers: dict, cookies: dict) -> dict:
    response = requests.get(f"{API_SERVER_URL}/me", headers=headers, cookies=cookies)
    response.raise_for_status()
    return response.json()


def _patch_personalization(headers: dict, cookies: dict, payload: dict) -> None:
    response = requests.patch(
        f"{API_SERVER_URL}/user/personalization",
        json=payload,
        headers=headers,
        cookies=cookies,
    )
    response.raise_for_status()


def test_personalization_round_trip(reset: None) -> None:  # noqa: ARG001
    user = UserManager.create()
    headers, cookies = _get_auth_headers(user)

    # baseline should have empty personalization
    me_initial = _get_me(headers, cookies)
    assert me_initial["personalization"]["name"] == ""
    assert me_initial["personalization"]["role"] == ""
    assert me_initial["personalization"]["use_memories"] is True
    assert me_initial["personalization"]["enable_memory_tool"] is True
    assert me_initial["personalization"]["memories"] == []

    payload = {
        "name": "Jane Doe",
        "role": "Developer advocate",
        "use_memories": True,
        "memories": [
            {"content": "Loves peanut butter"},
            {"content": "Prefers API docs"},
        ],
    }

    _patch_personalization(headers, cookies, payload)

    me_after = _get_me(headers, cookies)
    personalization = me_after["personalization"]

    assert personalization["name"] == payload["name"]
    assert personalization["role"] == payload["role"]
    assert personalization["use_memories"] is True
    returned_memories = personalization["memories"]
    assert len(returned_memories) == 2
    for mem in returned_memories:
        assert isinstance(mem["id"], int)
        assert isinstance(mem["content"], str)
    assert [m["content"] for m in returned_memories] == [
        "Prefers API docs",
        "Loves peanut butter",
    ]

    # update memories to empty
    payload["memories"] = []
    _patch_personalization(headers, cookies, payload)
    me_final = _get_me(headers, cookies)
    assert me_final["personalization"]["memories"] == []


def test_enable_memory_tool_round_trip(reset: None) -> None:  # noqa: ARG001
    user = UserManager.create()
    headers, cookies = _get_auth_headers(user)

    # default should be True
    me_initial = _get_me(headers, cookies)
    assert me_initial["personalization"]["enable_memory_tool"] is True

    # disable enable_memory_tool
    _patch_personalization(headers, cookies, {"enable_memory_tool": False})
    me_after = _get_me(headers, cookies)
    assert me_after["personalization"]["enable_memory_tool"] is False

    # re-enable
    _patch_personalization(headers, cookies, {"enable_memory_tool": True})
    me_reenabled = _get_me(headers, cookies)
    assert me_reenabled["personalization"]["enable_memory_tool"] is True


def test_enable_memory_tool_independent_of_use_memories(
    reset: None,  # noqa: ARG001
) -> None:
    user = UserManager.create()
    headers, cookies = _get_auth_headers(user)

    # set use_memories=False and enable_memory_tool=True simultaneously
    _patch_personalization(
        headers, cookies, {"use_memories": False, "enable_memory_tool": True}
    )
    me = _get_me(headers, cookies)
    assert me["personalization"]["use_memories"] is False
    assert me["personalization"]["enable_memory_tool"] is True

    # reverse: use_memories=True and enable_memory_tool=False
    _patch_personalization(
        headers, cookies, {"use_memories": True, "enable_memory_tool": False}
    )
    me = _get_me(headers, cookies)
    assert me["personalization"]["use_memories"] is True
    assert me["personalization"]["enable_memory_tool"] is False
