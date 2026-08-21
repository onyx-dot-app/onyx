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
