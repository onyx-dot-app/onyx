"""Unit tests for Canvas OAuth2 helpers and token refresh plumbing."""

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch
from urllib.parse import parse_qs
from urllib.parse import urlparse

import pytest

from onyx.connectors.canvas import oauth
from onyx.connectors.canvas.client import CanvasApiClient
from onyx.connectors.canvas.connector import CanvasConnector
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import CredentialsProviderInterface

CANVAS_URL = "https://school.instructure.com"
CLIENT_ID = "10000000000005"
CLIENT_SECRET = "shh"


def _token_response(
    status_code: int = 200, payload: dict[str, Any] | None = None
) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload if payload is not None else {}
    return response


def _api_response(
    status_code: int = 200,
    payload: Any = None,
    link: str = "",
) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload if payload is not None else {}
    response.headers = {"Link": link}
    response.reason = "Unauthorized" if status_code == 401 else "OK"
    return response


def _oauth_credential(now: float, expires_in: int = 3600) -> dict[str, Any]:
    return {
        oauth.CANVAS_ACCESS_TOKEN_KEY: "access-1",
        oauth.CANVAS_REFRESH_TOKEN_KEY: "refresh-1",
        oauth.CANVAS_TOKEN_EXPIRES_AT_KEY: int(now + expires_in),
        oauth.CANVAS_BASE_URL_KEY: CANVAS_URL,
        oauth.CANVAS_OAUTH_CLIENT_ID_KEY: CLIENT_ID,
    }


# ---------------------------------------------------------------------------
# Authorize URL / token parsing
# ---------------------------------------------------------------------------


def test_build_canvas_authorize_url_includes_required_params() -> None:
    url = oauth.build_canvas_authorize_url(
        canvas_base_url=f"{CANVAS_URL}/api/v1/",
        client_id=CLIENT_ID,
        redirect_uri="https://onyx.example.com/auth/lti/canvas-oauth/callback",
        state="state-123",
        scopes=["url:GET|/api/v1/courses", "url:GET|/api/v1/users/:id"],
        purpose="Onyx Virtual Tutor",
    )

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        f"{CANVAS_URL}/login/oauth2/auth"
    )
    assert query["client_id"] == [CLIENT_ID]
    assert query["response_type"] == ["code"]
    assert query["state"] == ["state-123"]
    assert query["redirect_uri"] == [
        "https://onyx.example.com/auth/lti/canvas-oauth/callback"
    ]
    assert query["scope"] == ["url:GET|/api/v1/courses url:GET|/api/v1/users/:id"]
    assert query["purpose"] == ["Onyx Virtual Tutor"]


def test_tokens_from_response_parses_user_and_defaults_expiry() -> None:
    tokens = oauth.CanvasOAuthTokens.from_token_response(
        {
            "access_token": "abc",
            "refresh_token": "def",
            "user": {"id": 42, "name": "Ada Instructor"},
        }
    )

    assert tokens.access_token == "abc"
    assert tokens.refresh_token == "def"
    assert tokens.expires_in == 3600
    assert tokens.canvas_user_id == 42
    assert tokens.canvas_user_name == "Ada Instructor"


def test_tokens_from_response_requires_access_token() -> None:
    with pytest.raises(oauth.CanvasOAuthError):
        oauth.CanvasOAuthTokens.from_token_response({"refresh_token": "def"})


def test_credential_json_from_tokens_keeps_refresh_token_and_extra_keys() -> None:
    existing = {
        **_oauth_credential(now=1_000),
        "respect_release_dates": False,
        oauth.CANVAS_TOKEN_INVALID_AT_KEY: 999,
    }
    refreshed = oauth.credential_json_from_tokens(
        oauth.CanvasOAuthTokens(access_token="access-2", expires_in=3600),
        canvas_base_url=CANVAS_URL,
        client_id=CLIENT_ID,
        existing=existing,
        now=2_000,
    )

    assert refreshed[oauth.CANVAS_ACCESS_TOKEN_KEY] == "access-2"
    # Canvas omits the refresh token on refresh responses; keep the old one.
    assert refreshed[oauth.CANVAS_REFRESH_TOKEN_KEY] == "refresh-1"
    assert refreshed[oauth.CANVAS_TOKEN_EXPIRES_AT_KEY] == 5_600
    assert refreshed["respect_release_dates"] is False
    assert oauth.CANVAS_TOKEN_INVALID_AT_KEY not in refreshed


# ---------------------------------------------------------------------------
# Refresh decision
# ---------------------------------------------------------------------------


def test_static_token_never_needs_refresh() -> None:
    assert (
        oauth.canvas_token_needs_refresh(
            {oauth.CANVAS_ACCESS_TOKEN_KEY: "pasted"}, now=0
        )
        is False
    )


def test_fresh_oauth_token_does_not_need_refresh() -> None:
    now = 10_000.0
    assert oauth.canvas_token_needs_refresh(_oauth_credential(now), now=now) is False


def test_oauth_token_near_expiry_needs_refresh() -> None:
    now = 10_000.0
    credential = _oauth_credential(
        now, expires_in=oauth.CANVAS_TOKEN_REFRESH_MARGIN_SECONDS - 1
    )
    assert oauth.canvas_token_needs_refresh(credential, now=now) is True


def test_oauth_token_without_expiry_needs_refresh() -> None:
    credential = _oauth_credential(now=0)
    del credential[oauth.CANVAS_TOKEN_EXPIRES_AT_KEY]
    assert oauth.canvas_token_needs_refresh(credential, now=0) is True


@patch("onyx.connectors.canvas.oauth.requests.post")
def test_refresh_if_needed_posts_refresh_grant(mock_post: MagicMock) -> None:
    now = 10_000.0
    credential = _oauth_credential(now, expires_in=60)
    mock_post.return_value = _token_response(
        payload={"access_token": "access-2", "expires_in": 3600}
    )

    refreshed, did_refresh = oauth.refresh_canvas_credential_json_if_needed(
        credential,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        now=now,
    )

    assert did_refresh is True
    assert refreshed[oauth.CANVAS_ACCESS_TOKEN_KEY] == "access-2"
    assert refreshed[oauth.CANVAS_TOKEN_EXPIRES_AT_KEY] == int(now + 3600)
    _, kwargs = mock_post.call_args
    assert mock_post.call_args[0][0] == f"{CANVAS_URL}/login/oauth2/token"
    assert kwargs["data"] == {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": "refresh-1",
    }


@patch("onyx.connectors.canvas.oauth.requests.post")
def test_refresh_if_needed_skips_fresh_token(mock_post: MagicMock) -> None:
    now = 10_000.0
    refreshed, did_refresh = oauth.refresh_canvas_credential_json_if_needed(
        _oauth_credential(now),
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        now=now,
    )

    assert did_refresh is False
    assert refreshed[oauth.CANVAS_ACCESS_TOKEN_KEY] == "access-1"
    mock_post.assert_not_called()


@patch("onyx.connectors.canvas.oauth.requests.post")
def test_refresh_if_needed_without_client_config_keeps_token(
    mock_post: MagicMock,
) -> None:
    now = 10_000.0
    refreshed, did_refresh = oauth.refresh_canvas_credential_json_if_needed(
        _oauth_credential(now, expires_in=1),
        client_id=None,
        client_secret=None,
        now=now,
    )

    assert did_refresh is False
    assert refreshed[oauth.CANVAS_ACCESS_TOKEN_KEY] == "access-1"
    mock_post.assert_not_called()


@patch("onyx.connectors.canvas.oauth.requests.post")
def test_invalid_grant_is_permanent(mock_post: MagicMock) -> None:
    mock_post.return_value = _token_response(
        status_code=400,
        payload={
            "error": "invalid_grant",
            "error_description": "refresh_token not found",
        },
    )

    with pytest.raises(oauth.CanvasOAuthError) as exc_info:
        oauth.refresh_canvas_credential_json(
            _oauth_credential(now=0),
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
        )

    assert exc_info.value.permanent is True
    assert exc_info.value.error_code == "invalid_grant"
    assert "refresh_token not found" in str(exc_info.value)


@patch("onyx.connectors.canvas.oauth.requests.post")
def test_server_error_is_transient(mock_post: MagicMock) -> None:
    mock_post.return_value = _token_response(status_code=503, payload={})

    with pytest.raises(oauth.CanvasOAuthError) as exc_info:
        oauth.refresh_canvas_credential_json(
            _oauth_credential(now=0),
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
        )

    assert exc_info.value.permanent is False


@patch("onyx.connectors.canvas.oauth.requests.post")
def test_exchange_authorization_code_posts_code_grant(mock_post: MagicMock) -> None:
    mock_post.return_value = _token_response(
        payload={
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "expires_in": 3600,
            "user": {"id": 7, "name": "Ada"},
        }
    )

    tokens = oauth.exchange_canvas_authorization_code(
        canvas_base_url=CANVAS_URL,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri="https://onyx.example.com/auth/lti/canvas-oauth/callback",
        code="code-1",
    )

    assert tokens.refresh_token == "refresh-1"
    assert tokens.canvas_user_id == 7
    _, kwargs = mock_post.call_args
    assert kwargs["data"]["grant_type"] == "authorization_code"
    assert kwargs["data"]["code"] == "code-1"
    assert kwargs["data"]["redirect_uri"] == (
        "https://onyx.example.com/auth/lti/canvas-oauth/callback"
    )


# ---------------------------------------------------------------------------
# CanvasApiClient 401 retry
# ---------------------------------------------------------------------------


@patch("onyx.connectors.canvas.client.rl_requests")
def test_client_retries_once_with_refreshed_token_on_401(
    mock_requests: MagicMock,
) -> None:
    mock_requests.get.side_effect = [
        _api_response(status_code=401, payload={"error": "Invalid access token"}),
        _api_response(payload={"id": 1}),
    ]
    refresher = MagicMock(return_value="access-2")
    client = CanvasApiClient(
        bearer_token="access-1",
        canvas_base_url=CANVAS_URL,
        token_refresher=refresher,
    )

    payload, _ = client.get("courses/1")

    assert payload == {"id": 1}
    refresher.assert_called_once()
    first_headers = mock_requests.get.call_args_list[0].kwargs["headers"]
    second_headers = mock_requests.get.call_args_list[1].kwargs["headers"]
    assert first_headers["Authorization"] == "Bearer access-1"
    assert second_headers["Authorization"] == "Bearer access-2"
    assert client.bearer_token == "access-2"


@patch("onyx.connectors.canvas.client.rl_requests")
def test_client_does_not_retry_when_refresher_returns_none(
    mock_requests: MagicMock,
) -> None:
    mock_requests.get.return_value = _api_response(
        status_code=401, payload={"error": "Invalid access token"}
    )
    client = CanvasApiClient(
        bearer_token="access-1",
        canvas_base_url=CANVAS_URL,
        token_refresher=MagicMock(return_value=None),
    )

    with pytest.raises(Exception) as exc_info:
        client.get("courses/1")

    assert getattr(exc_info.value, "status_code", None) == 401
    assert mock_requests.get.call_count == 1


@patch("onyx.connectors.canvas.client.rl_requests")
def test_client_without_refresher_raises_on_401(mock_requests: MagicMock) -> None:
    mock_requests.get.return_value = _api_response(
        status_code=401, payload={"error": "Invalid access token"}
    )
    client = CanvasApiClient(bearer_token="access-1", canvas_base_url=CANVAS_URL)

    with pytest.raises(Exception):
        client.get("courses/1")

    assert mock_requests.get.call_count == 1


# ---------------------------------------------------------------------------
# CanvasConnector + credentials provider
# ---------------------------------------------------------------------------


class _FakeCredentialsProvider(
    CredentialsProviderInterface["_FakeCredentialsProvider"]
):
    def __init__(self, credential_json: dict[str, Any]) -> None:
        self.credential_json = dict(credential_json)
        self.set_calls: list[dict[str, Any]] = []
        self.lock_depth = 0

    def __enter__(self) -> "_FakeCredentialsProvider":
        self.lock_depth += 1
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.lock_depth -= 1

    def get_tenant_id(self) -> str | None:
        return None

    def get_provider_key(self) -> str:
        return "canvas-test"

    def get_credentials(self) -> dict[str, Any]:
        return dict(self.credential_json)

    def set_credentials(self, credential_json: dict[str, Any]) -> None:
        self.credential_json = dict(credential_json)
        self.set_calls.append(dict(credential_json))

    def is_dynamic(self) -> bool:
        return True


def _patch_oauth_client_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "onyx.connectors.canvas.connector.LTI_CANVAS_OAUTH_CLIENT_ID", CLIENT_ID
    )
    monkeypatch.setattr(
        "onyx.connectors.canvas.connector.LTI_CANVAS_OAUTH_CLIENT_SECRET",
        CLIENT_SECRET,
    )


@patch("onyx.connectors.canvas.oauth.requests.post")
@patch("onyx.connectors.canvas.client.rl_requests")
def test_connector_refreshes_expiring_token_through_provider(
    mock_requests: MagicMock,
    mock_post: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_oauth_client_config(monkeypatch)
    # Token expired 10 minutes ago -> refreshed before the first API call.
    import time

    provider = _FakeCredentialsProvider(
        _oauth_credential(now=time.time() - 4200, expires_in=3600)
    )
    mock_post.return_value = _token_response(
        payload={"access_token": "access-2", "expires_in": 3600}
    )
    mock_requests.get.return_value = _api_response(
        payload={"id": 1, "name": "Intro", "course_code": "CS1"}
    )

    connector = CanvasConnector(canvas_base_url=CANVAS_URL, course_ids=[1])
    connector.set_credentials_provider(provider)

    assert provider.set_calls, "refreshed credentials should be persisted"
    assert provider.set_calls[-1][oauth.CANVAS_ACCESS_TOKEN_KEY] == "access-2"
    assert provider.lock_depth == 0
    headers = mock_requests.get.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer access-2"


@patch("onyx.connectors.canvas.oauth.requests.post")
@patch("onyx.connectors.canvas.client.rl_requests")
def test_connector_marks_credential_invalid_when_refresh_is_rejected(
    mock_requests: MagicMock,
    mock_post: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_oauth_client_config(monkeypatch)
    provider = _FakeCredentialsProvider(_oauth_credential(now=0, expires_in=1))
    mock_post.return_value = _token_response(
        status_code=400, payload={"error": "invalid_grant"}
    )

    connector = CanvasConnector(canvas_base_url=CANVAS_URL, course_ids=[1])
    with pytest.raises(CredentialExpiredError):
        connector.set_credentials_provider(provider)

    assert oauth.CANVAS_TOKEN_INVALID_AT_KEY in provider.credential_json
    mock_requests.get.assert_not_called()


@patch("onyx.connectors.canvas.oauth.requests.post")
@patch("onyx.connectors.canvas.client.rl_requests")
def test_connector_transient_refresh_failure_is_not_credential_expiry(
    mock_requests: MagicMock,
    mock_post: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_oauth_client_config(monkeypatch)
    provider = _FakeCredentialsProvider(_oauth_credential(now=0, expires_in=1))
    mock_post.return_value = _token_response(status_code=502, payload={})

    connector = CanvasConnector(canvas_base_url=CANVAS_URL, course_ids=[1])
    with pytest.raises(UnexpectedValidationError):
        connector.set_credentials_provider(provider)

    assert oauth.CANVAS_TOKEN_INVALID_AT_KEY not in provider.credential_json
    mock_requests.get.assert_not_called()


@patch("onyx.connectors.canvas.oauth.requests.post")
@patch("onyx.connectors.canvas.client.rl_requests")
def test_connector_reuses_token_refreshed_by_another_worker_on_401(
    mock_requests: MagicMock,
    mock_post: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_oauth_client_config(monkeypatch)
    import time

    now = time.time()
    provider = _FakeCredentialsProvider(_oauth_credential(now))
    mock_requests.get.side_effect = [
        _api_response(payload={"id": 1, "name": "Intro", "course_code": "CS1"}),
        _api_response(status_code=401, payload={"error": "Invalid access token"}),
        _api_response(payload=[{"id": 1, "name": "Intro"}]),
    ]

    connector = CanvasConnector(canvas_base_url=CANVAS_URL, course_ids=[1])
    connector.set_credentials_provider(provider)

    # Simulate a sibling worker having refreshed the shared credential.
    provider.credential_json[oauth.CANVAS_ACCESS_TOKEN_KEY] = "access-other"
    provider.credential_json[oauth.CANVAS_TOKEN_EXPIRES_AT_KEY] = int(now + 3600)

    connector.validate_connector_settings()

    mock_post.assert_not_called()
    last_headers = mock_requests.get.call_args_list[-1].kwargs["headers"]
    assert last_headers["Authorization"] == "Bearer access-other"


@patch("onyx.connectors.canvas.client.rl_requests")
def test_connector_static_token_is_not_refreshed(
    mock_requests: MagicMock,
) -> None:
    provider = _FakeCredentialsProvider({oauth.CANVAS_ACCESS_TOKEN_KEY: "pasted"})
    mock_requests.get.return_value = _api_response(
        payload={"id": 1, "name": "Intro", "course_code": "CS1"}
    )

    connector = CanvasConnector(canvas_base_url=CANVAS_URL, course_ids=[1])
    connector.set_credentials_provider(provider)

    assert provider.set_calls == []
    assert connector._refresh_access_token() is None
