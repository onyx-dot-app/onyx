"""Session initialization has a longer timeout without changing later requests."""

import httpx
import pytest

from onyx.server.features.build.sandbox.opencode.serve_client import (
    ClientTimeouts,
    OpencodeServeClient,
)


@pytest.mark.parametrize("session_id", [None, "ses_existing", "ses_missing"])
@pytest.mark.parametrize(
    "timeouts,connect_timeout,request_timeout,session_init_timeout",
    [
        (None, 5.0, 30.0, 90.0),
        (
            ClientTimeouts(
                connect_timeout=1.0, request_timeout=2.0, session_init_timeout=9.0
            ),
            1.0,
            2.0,
            9.0,
        ),
    ],
)
def test_initialization_timeout_does_not_change_normal_requests(
    session_id: str | None,
    timeouts: ClientTimeouts | None,
    connect_timeout: float,
    request_timeout: float,
    session_init_timeout: float,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/session/ses_missing":
            return httpx.Response(404)
        return httpx.Response(200, json={"id": "ses_existing"})

    with OpencodeServeClient(
        base_url="http://test.invalid:4096",
        password=None,
        timeouts=timeouts,
        transport=httpx.MockTransport(handler),
    ) as client:
        directory = "/workspace/sessions/test"
        assert client.ensure_session(session_id, directory=directory) == "ses_existing"
        initialization_requests = list(requests)
        requests.clear()

        client._post_prompt_async(
            "ses_existing", "Hello", None, None, directory=directory
        )
        client.get_message("ses_existing", "msg_existing", directory=directory)
        client.abort("ses_existing", directory=directory)
        assert client.delete_session("ses_existing", directory=directory)
        normal_requests = list(requests)
        requests.clear()

        assert client.health_check()

    assert len(initialization_requests) == (2 if session_id == "ses_missing" else 1)
    for request in initialization_requests:
        assert request.extensions["timeout"] == {
            "connect": connect_timeout,
            "pool": connect_timeout,
            "read": session_init_timeout,
            "write": session_init_timeout,
        }
        assert request.url.params["directory"] == directory
    assert len(normal_requests) == 4
    for request in normal_requests:
        assert request.extensions["timeout"] == {
            "connect": connect_timeout,
            "pool": connect_timeout,
            "read": request_timeout,
            "write": request_timeout,
        }
    assert requests[0].extensions["timeout"] == dict.fromkeys(
        ("connect", "pool", "read", "write"), connect_timeout
    )
