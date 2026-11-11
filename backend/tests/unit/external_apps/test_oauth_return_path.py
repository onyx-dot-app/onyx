from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.external_apps.models import OAuthCallbackRequest
from onyx.server.features.build.external_apps.oauth import (
    _ExternalAppOAuthAttemptPayload,
    handle_external_app_oauth_callback,
    start_external_app_oauth,
)
from tests.unit.external_apps.test_oauth_flow import _configure_route, _user


@pytest.mark.parametrize(
    "path", ["https://example.com", "//example.com", "/\\example.com", "/app\n"]
)
def test_oauth_attempt_rejects_external_or_unsafe_return_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        _ExternalAppOAuthAttemptPayload(
            external_app_id=7, configuration_fingerprint="a" * 64, return_path=path
        )


def test_oauth_attempt_round_trips_member_completion_path() -> None:
    path = (
        "/app/plugins/oauth/complete?pluginKind=external-app&pluginId=7&attempt=nonce"
    )
    payload = _ExternalAppOAuthAttemptPayload(
        external_app_id=7, configuration_fingerprint="a" * 64, return_path=path
    )
    assert (
        _ExternalAppOAuthAttemptPayload.model_validate_json(
            payload.model_dump_json()
        ).return_path
        == path
    )


def test_oauth_attempt_without_return_path_uses_default() -> None:
    payload = _ExternalAppOAuthAttemptPayload(
        external_app_id=7, configuration_fingerprint="a" * 64
    )
    assert payload.return_path is None


def test_oauth_start_rejects_unsafe_return_before_loading_app() -> None:
    with patch(
        "onyx.server.features.build.external_apps.oauth.get_external_app_by_id"
    ) as get_app:
        with pytest.raises(OnyxError):
            start_external_app_oauth(
                7, user=MagicMock(), db_session=MagicMock(), return_path="//example.com"
            )
        get_app.assert_not_called()


@pytest.mark.parametrize(
    "return_path", [None, "/app/plugins/oauth/complete?attempt=nonce"]
)
def test_callback_preserves_return_path_after_saving_credentials(
    monkeypatch: pytest.MonkeyPatch, return_path: str | None
) -> None:
    app, _, db_session, _ = _configure_route(monkeypatch)
    user = _user("owner")
    start = start_external_app_oauth(
        app.id, user=user, db_session=db_session, return_path=return_path
    )
    state = parse_qs(urlparse(start.authorize_url).query)["state"][0]
    request = OAuthCallbackRequest(code="code", state=state)
    result = handle_external_app_oauth_callback(
        request, user=user, db_session=db_session
    )
    assert result.success is True
    assert result.external_app_id == 7
    assert result.return_path == return_path
    with pytest.raises(OnyxError):
        handle_external_app_oauth_callback(request, user=user, db_session=db_session)
