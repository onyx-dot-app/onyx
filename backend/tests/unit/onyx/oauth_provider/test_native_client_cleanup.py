import pytest

from tests.external_dependency_unit.oauth_provider.test_native_clients import (
    NativeOAuthServer,
    NativeRequestEvent,
)


def _server() -> NativeOAuthServer:
    return NativeOAuthServer(
        base_url="http://localhost:3000",
        mcp_path="/mcp",
        user_id="test-user",
        cookie_name="test-session",
        session_token="test-token",
    )


def test_registered_clients_survive_event_resets() -> None:
    server: NativeOAuthServer = _server()
    server.record(
        NativeRequestEvent(
            method="POST",
            path="/oauth-provider/register",
            authorization=None,
            status_code=201,
            rpc_method=None,
            response_body='{"client_id": "owned-client"}',
        )
    )
    server.clear_events()

    assert server.events == []
    assert server.registered_client_ids() == {"owned-client"}
    returned_ids: set[str] = server.registered_client_ids()
    returned_ids.clear()
    assert server.registered_client_ids() == {"owned-client"}


@pytest.mark.parametrize(
    ("method", "path", "status_code", "response_body"),
    [
        ("POST", "/oauth-provider/register", 400, '{"client_id": "foreign"}'),
        ("POST", "/oauth-provider/register", None, '{"client_id": "foreign"}'),
        ("GET", "/oauth-provider/register", 200, '{"client_id": "foreign"}'),
        ("POST", "/other/register", 201, '{"client_id": "foreign"}'),
        ("POST", "/oauth-provider/register", 201, "invalid-json"),
        ("POST", "/oauth-provider/register", 201, "[]"),
        ("POST", "/oauth-provider/register", 201, '{"client_id": 42}'),
    ],
)
def test_cleanup_excludes_unowned_registration_responses(
    method: str, path: str, status_code: int | None, response_body: str
) -> None:
    server: NativeOAuthServer = _server()
    server.record(
        NativeRequestEvent(
            method=method,
            path=path,
            authorization=None,
            status_code=status_code,
            rpc_method=None,
            response_body=response_body,
        )
    )

    assert server.registered_client_ids() == set()
