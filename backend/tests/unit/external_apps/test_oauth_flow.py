from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from sqlalchemy.orm import Session

from onyx.auth.pkce import compute_s256_challenge
from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp, User
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.base import OAuthExternalAppProvider
from onyx.external_apps.providers.registry import PROVIDERS
from onyx.server.features.build.external_apps import oauth as oauth_route
from onyx.server.features.build.external_apps.models import OAuthCallbackRequest
from tests.unit.fakes import FakeCache


class _OrganizationCredentials:
    def __init__(self) -> None:
        self.values = {
            "client_id": "linear-client-id",
            "client_secret": "linear-client-secret",
        }

    def get_value(self, **_: object) -> dict[str, str]:
        return self.values.copy()


def _app(credentials: _OrganizationCredentials) -> ExternalApp:
    return cast(
        ExternalApp,
        SimpleNamespace(
            id=7,
            name="Linear",
            enabled=True,
            app_type=ExternalAppType.LINEAR,
            organization_credentials=credentials,
        ),
    )


def _user(user_id: str) -> User:
    return cast(User, SimpleNamespace(id=user_id))


def _authorize_query(
    *,
    app: ExternalApp,
    user: User,
    db_session: Session,
) -> dict[str, list[str]]:
    response = oauth_route.start_external_app_oauth(
        external_app_id=app.id,
        user=user,
        db_session=db_session,
    )
    return parse_qs(urlparse(response.authorize_url).query)


def _successful_token_response() -> requests.Response:
    response = MagicMock(spec=requests.Response)
    response.status_code = 200
    response.json.return_value = {
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "expires_in": 3600,
        "scope": "read,write",
        "token_type": "Bearer",
    }
    return response


def _configure_route(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ExternalApp, _OrganizationCredentials, MagicMock, MagicMock]:
    cache = FakeCache()
    credentials = _OrganizationCredentials()
    app = _app(credentials)
    db_session = MagicMock(spec=Session)
    token_post = MagicMock(return_value=_successful_token_response())
    persist_credentials = MagicMock()

    monkeypatch.setattr(oauth_route, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(oauth_route, "get_external_app_by_id", lambda *_: app)
    monkeypatch.setattr(oauth_route.requests, "post", token_post)
    monkeypatch.setattr(
        oauth_route,
        "upsert_external_app_user_credential",
        persist_credentials,
    )
    monkeypatch.setattr(oauth_route, "push_skills_for_users", MagicMock())
    return app, credentials, db_session, token_post


def test_overlapping_pkce_attempts_use_their_own_verifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _, db_session, token_post = _configure_route(monkeypatch)
    owner = _user("owner")

    first = _authorize_query(app=app, user=owner, db_session=db_session)
    second = _authorize_query(app=app, user=owner, db_session=db_session)

    first_state = first["state"][0]
    second_state = second["state"][0]
    assert first_state != second_state
    for query in (first, second):
        assert query["code_challenge_method"] == ["S256"]
        assert "code_verifier" not in query

    for code, state in (("second-code", second_state), ("first-code", first_state)):
        oauth_route.handle_external_app_oauth_callback(
            OAuthCallbackRequest(code=code, state=state),
            user=owner,
            db_session=db_session,
        )

    challenges_by_state = {
        first_state: first["code_challenge"][0],
        second_state: second["code_challenge"][0],
    }
    states_by_code = {"first-code": first_state, "second-code": second_state}
    token_request_bodies: list[dict[str, Any]] = [
        call.kwargs["data"] for call in token_post.call_args_list
    ]
    assert {body["code"] for body in token_request_bodies} == set(states_by_code)
    for body in token_request_bodies:
        state = states_by_code[body["code"]]
        assert (
            compute_s256_challenge(body["code_verifier"]) == challenges_by_state[state]
        )


def test_attempt_is_owner_bound_and_claimed_before_token_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _, db_session, token_post = _configure_route(monkeypatch)
    owner = _user("owner")
    state = _authorize_query(app=app, user=owner, db_session=db_session)["state"][0]

    with pytest.raises(
        OnyxError, match="Invalid or expired OAuth authorization attempt"
    ):
        oauth_route.handle_external_app_oauth_callback(
            OAuthCallbackRequest(code="stolen-code", state=state),
            user=_user("other-user"),
            db_session=db_session,
        )
    token_post.assert_not_called()

    token_post.side_effect = requests.RequestException("provider unavailable")
    with pytest.raises(OnyxError, match="Could not reach Linear to complete OAuth"):
        oauth_route.handle_external_app_oauth_callback(
            OAuthCallbackRequest(code="owner-code", state=state),
            user=owner,
            db_session=db_session,
        )
    assert token_post.call_count == 1

    with pytest.raises(
        OnyxError, match="Invalid or expired OAuth authorization attempt"
    ):
        oauth_route.handle_external_app_oauth_callback(
            OAuthCallbackRequest(code="retried-code", state=state),
            user=owner,
            db_session=db_session,
        )
    assert token_post.call_count == 1


def test_callback_rejects_configuration_changed_after_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, credentials, db_session, token_post = _configure_route(monkeypatch)
    user = _user("owner")
    query = _authorize_query(app=app, user=user, db_session=db_session)
    credentials.values["client_secret"] = "rotated-client-secret"

    with pytest.raises(
        OnyxError,
        match="External app OAuth configuration changed while authorization was pending",
    ):
        oauth_route.handle_external_app_oauth_callback(
            OAuthCallbackRequest(code="authorization-code", state=query["state"][0]),
            user=user,
            db_session=db_session,
        )

    token_post.assert_not_called()


@pytest.mark.parametrize(
    ("app_type", "token_body", "expected_scopes", "json_encoded"),
    [
        (
            ExternalAppType.LINEAR,
            {
                "access_token": "access",
                "refresh_token": "refresh",
                "scope": "read,write",
                "expires_in": 3600,
            },
            ["read", "write"],
            False,
        ),
        (
            ExternalAppType.GITHUB,
            {"access_token": "access", "scope": "repo,read:org"},
            ["repo", "read:org"],
            False,
        ),
        (
            ExternalAppType.SLACK,
            {
                "ok": True,
                "access_token": "bot-token-must-not-be-stored",
                "authed_user": {
                    "access_token": "access",
                    "scope": "chat:write,search:read",
                },
            },
            ["chat:write", "search:read"],
            False,
        ),
        (
            ExternalAppType.NOTION,
            {"access_token": "access", "workspace_id": "workspace"},
            None,
            True,
        ),
        (
            ExternalAppType.HUBSPOT,
            {"access_token": "access", "refresh_token": "refresh"},
            ["oauth", "crm.objects.contacts.read"],
            False,
        ),
    ],
)
def test_callback_preserves_provider_exchange_and_grant(
    monkeypatch: pytest.MonkeyPatch,
    app_type: ExternalAppType,
    token_body: dict[str, Any],
    expected_scopes: list[str] | None,
    json_encoded: bool,
) -> None:
    app, _, db_session, token_post = _configure_route(monkeypatch)
    app.app_type = app_type
    owner = _user("owner")
    persist = MagicMock()
    push = MagicMock()
    monkeypatch.setattr(oauth_route, "upsert_external_app_user_credential", persist)
    monkeypatch.setattr(oauth_route, "push_skills_for_users", push)
    info_response = MagicMock(spec=requests.Response)
    info_response.json.return_value = {"scopes": expected_scopes}
    monkeypatch.setattr(
        oauth_route.requests, "get", MagicMock(return_value=info_response)
    )
    token_post.return_value.json.return_value = token_body

    query = _authorize_query(app=app, user=owner, db_session=db_session)
    uses_pkce = app_type in (ExternalAppType.LINEAR, ExternalAppType.GITHUB)
    assert ("code_challenge" in query) == uses_pkce
    if app_type == ExternalAppType.SLACK:
        assert "user_scope" in query
        assert "scope" not in query
    result = oauth_route.handle_external_app_oauth_callback(
        OAuthCallbackRequest(code="auth-code", state=query["state"][0]),
        user=owner,
        db_session=db_session,
    )
    assert result.success
    assert result.external_app_id == app.id
    request = token_post.call_args.kwargs
    body = request["json" if json_encoded else "data"]
    assert request["data" if json_encoded else "json"] is None
    assert body["code"] == "auth-code"
    assert ("code_verifier" in body) == uses_pkce
    if json_encoded:
        assert request["headers"]["Authorization"].startswith("Basic ")
        assert "client_id" not in body
        assert "client_secret" not in body
    else:
        assert body["client_id"] == "linear-client-id"
        assert body["client_secret"] == "linear-client-secret"
    persisted = persist.call_args.kwargs
    assert persisted["user_credentials"]["access_token"] == "access"
    if token_body.get("refresh_token"):
        assert persisted["user_credentials"]["refresh_token"] == "refresh"
    if token_body.get("expires_in"):
        assert "expires_at" in persisted["user_credentials"]
    assert persisted["granted_scopes"] == expected_scopes
    assert persisted["user_id"] == owner.id
    push.assert_called_once_with({owner.id}, db_session)
    db_session.commit.assert_called_once()


@pytest.mark.parametrize("malformed_body", [None, [], "not-an-object"])
def test_callback_rejects_non_object_token_response(
    monkeypatch: pytest.MonkeyPatch, malformed_body: object
) -> None:
    app, _, db_session, token_post = _configure_route(monkeypatch)
    owner = _user("owner")
    query = _authorize_query(app=app, user=owner, db_session=db_session)
    token_post.return_value.json.return_value = malformed_body
    with pytest.raises(OnyxError, match="invalid token response") as error:
        oauth_route.handle_external_app_oauth_callback(
            OAuthCallbackRequest(code="code", state=query["state"][0]),
            user=owner,
            db_session=db_session,
        )
    assert error.value.status_code == 502
    db_session.commit.assert_not_called()


def test_non_json_success_response_is_a_gateway_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _, db_session, token_post = _configure_route(monkeypatch)
    owner = _user("owner")
    query = _authorize_query(app=app, user=owner, db_session=db_session)
    token_post.return_value.json.side_effect = ValueError("invalid JSON")
    with pytest.raises(OnyxError, match="non-JSON") as error:
        oauth_route.handle_external_app_oauth_callback(
            OAuthCallbackRequest(code="code", state=query["state"][0]),
            user=owner,
            db_session=db_session,
        )
    assert error.value.status_code == 502


@pytest.mark.parametrize("removed", [True, False])
def test_callback_rechecks_app_availability(
    monkeypatch: pytest.MonkeyPatch, removed: bool
) -> None:
    app, _, db_session, token_post = _configure_route(monkeypatch)
    owner = _user("owner")
    query = _authorize_query(app=app, user=owner, db_session=db_session)
    if removed:
        monkeypatch.setattr(oauth_route, "get_external_app_by_id", lambda *_: None)
    else:
        app.enabled = False
    with pytest.raises(OnyxError, match="no longer exists|disabled"):
        oauth_route.handle_external_app_oauth_callback(
            OAuthCallbackRequest(code="code", state=query["state"][0]),
            user=owner,
            db_session=db_session,
        )
    token_post.assert_not_called()


@pytest.mark.parametrize(
    "app_type",
    [
        key
        for key, provider in PROVIDERS.items()
        if isinstance(provider, OAuthExternalAppProvider)
    ],
)
def test_all_oauth_providers_preserve_authorization_parameters(
    monkeypatch: pytest.MonkeyPatch, app_type: ExternalAppType
) -> None:
    app, _, db_session, _ = _configure_route(monkeypatch)
    app.app_type = app_type
    provider = PROVIDERS[app_type]
    assert isinstance(provider, OAuthExternalAppProvider)
    oauth = provider.spec.oauth
    query = _authorize_query(app=app, user=_user("owner"), db_session=db_session)
    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["linear-client-id"]
    assert "client_secret" not in query
    if oauth.scope:
        assert query[oauth.scope_param] == [oauth.scope]
    if oauth.optional_scope:
        assert query[oauth.optional_scope_param] == [oauth.optional_scope]
    for key, value in oauth.extra_authorize_params.items():
        assert query[key] == [value]
    assert ("code_challenge" in query) == oauth.supports_pkce


@pytest.mark.parametrize(
    ("app_type", "token_body"),
    [
        (ExternalAppType.LINEAR, {"access_token": 123}),
        (ExternalAppType.NOTION, {"access_token": ["not-a-token"]}),
        (ExternalAppType.SLACK, {"authed_user": ["invalid"]}),
        (ExternalAppType.SLACK, {"authed_user": {"access_token": 123}}),
        (
            ExternalAppType.SLACK,
            {"authed_user": {"access_token": "token"}, "team": "invalid"},
        ),
    ],
)
def test_callback_rejects_invalid_provider_credentials(
    monkeypatch: pytest.MonkeyPatch,
    app_type: ExternalAppType,
    token_body: dict[str, Any],
) -> None:
    app, _, db_session, token_post = _configure_route(monkeypatch)
    app.app_type = app_type
    persist = MagicMock()
    monkeypatch.setattr(oauth_route, "upsert_external_app_user_credential", persist)
    owner = _user("owner")
    query = _authorize_query(app=app, user=owner, db_session=db_session)
    token_post.return_value.json.return_value = token_body
    callback = OAuthCallbackRequest(code="code", state=query["state"][0])
    with pytest.raises(OnyxError, match="invalid") as error:
        oauth_route.handle_external_app_oauth_callback(
            callback, user=owner, db_session=db_session
        )
    assert error.value.status_code == 502
    persist.assert_not_called()
    db_session.commit.assert_not_called()
    with pytest.raises(OnyxError, match="Invalid or expired"):
        oauth_route.handle_external_app_oauth_callback(
            callback, user=owner, db_session=db_session
        )
    token_post.assert_called_once()


@pytest.mark.parametrize("status_code", [301, 302, 303, 307, 308])
def test_callback_does_not_follow_token_redirects(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    app, _, db_session, token_post = _configure_route(monkeypatch)
    persist = MagicMock()
    monkeypatch.setattr(oauth_route, "upsert_external_app_user_credential", persist)
    owner = _user("owner")
    query = _authorize_query(app=app, user=owner, db_session=db_session)
    token_post.return_value.status_code = status_code
    with pytest.raises(OnyxError, match="redirected") as error:
        oauth_route.handle_external_app_oauth_callback(
            OAuthCallbackRequest(code="code", state=query["state"][0]),
            user=owner,
            db_session=db_session,
        )
    assert error.value.status_code == 502
    assert token_post.call_args.kwargs["allow_redirects"] is False
    persist.assert_not_called()
    db_session.commit.assert_not_called()
