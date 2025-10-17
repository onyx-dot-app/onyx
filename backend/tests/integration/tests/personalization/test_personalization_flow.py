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


def test_personalization_round_trip(reset: None) -> None:
    user = UserManager.create()
    headers, cookies = _get_auth_headers(user)

    # baseline should have empty personalization
    me_initial = _get_me(headers, cookies)
    assert me_initial["personalization"]["name"] == ""
    assert me_initial["personalization"]["role"] == ""
    assert me_initial["personalization"]["use_memories"] is True
    assert me_initial["personalization"]["memories"] == []

    payload = {
        "name": "Jane Doe",
        "role": "Developer advocate",
        "use_memories": True,
        "memories": ["Loves peanut butter", "Prefers API docs"],
    }

    _patch_personalization(headers, cookies, payload)

    me_after = _get_me(headers, cookies)
    personalization = me_after["personalization"]

    assert personalization["name"] == payload["name"]
    assert personalization["role"] == payload["role"]
    assert personalization["use_memories"] is True
    assert personalization["memories"] == payload["memories"]

    # update memories to empty
    payload["memories"] = []
    _patch_personalization(headers, cookies, payload)
    me_final = _get_me(headers, cookies)
    assert me_final["personalization"]["memories"] == []
