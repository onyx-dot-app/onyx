"""The suggested-questions routes are mounted only on the Playground. The test
stack runs without IS_PLAYGROUND, so they must not exist there; behavior on
the Playground is covered by the unit and external-dependency tests."""

from onyx.configs.constants import DEFAULT_PERSONA_ID, FASTAPI_USERS_AUTH_COOKIE_NAME
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.user import UserManager

_URL = f"{API_SERVER_URL}/chat/suggested-questions"


def test_off_the_playground_the_routes_are_not_mounted() -> None:
    user = UserManager.create()
    cookies = {
        FASTAPI_USERS_AUTH_COOKIE_NAME: user.cookies[FASTAPI_USERS_AUTH_COOKIE_NAME]
    }

    listed = client.get(
        _URL,
        params={"agent_id": DEFAULT_PERSONA_ID, "seed": 7},
        headers=user.headers,
        cookies=cookies,
    )
    used = client.post(
        f"{_URL}/used",
        json={"question_id": "q-anything"},
        headers=user.headers,
        cookies=cookies,
    )

    assert (listed.status_code, used.status_code) == (404, 404)
