from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
import requests
from pydantic import ValidationError
from sqlalchemy.orm import Session

from onyx.auth import oauth_token_manager
from onyx.auth.pkce import compute_s256_challenge
from onyx.db.models import OAuthConfig, User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.oauth_config import api as oauth_config_api
from onyx.server.features.oauth_config.models import OAuthInitiateRequest
from tests.unit.fakes import FakeCache


def _oauth_config() -> OAuthConfig:
    return cast(
        OAuthConfig,
        SimpleNamespace(
            id=17,
            authorization_url="https://provider.example.com/authorize",
            token_url="https://provider.example.com/token",
            client_id="client-id",
            client_secret="client-secret",
            scopes=["read", "write"],
            additional_params={"prompt": "consent"},
            supports_pkce=False,
        ),
    )


def _user() -> User:
    return cast(User, SimpleNamespace(id=uuid4()))


def _successful_token_response() -> requests.Response:
    response = MagicMock(spec=requests.Response)
    response.json.return_value = {
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "expires_in": 3600,
    }
    return response


def _configure_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[OAuthConfig, User, MagicMock, MagicMock]:
    cache = FakeCache()
    oauth_config = _oauth_config()
    user = _user()
    db_session = MagicMock(spec=Session)
    token_post = MagicMock(return_value=_successful_token_response())

    monkeypatch.setattr(oauth_config_api, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(oauth_config_api, "get_oauth_config", lambda *_: oauth_config)
    monkeypatch.setattr(oauth_config_api, "upsert_user_oauth_token", MagicMock())
    monkeypatch.setattr(
        oauth_token_manager, "validate_oauth_endpoint_url", lambda *_: None
    )
    monkeypatch.setattr(oauth_token_manager.requests, "post", token_post)
    return oauth_config, user, db_session, token_post


def _initiate(
    *,
    oauth_config: OAuthConfig,
    user: User,
    db_session: Session,
    return_path: str = "/app?action=17",
) -> tuple[str, dict[str, list[str]]]:
    response = oauth_config_api.initiate_oauth_flow(
        OAuthInitiateRequest(
            oauth_config_id=oauth_config.id,
            return_path=return_path,
        ),
        db_session=db_session,
        user=user,
    )
    return response.state, parse_qs(urlparse(response.authorization_url).query)


def test_overlapping_attempts_use_their_own_server_side_pkce_verifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oauth_config, user, db_session, token_post = _configure_flow(monkeypatch)
    oauth_config.supports_pkce = True
    first_state, first_query = _initiate(
        oauth_config=oauth_config, user=user, db_session=db_session
    )
    second_state, second_query = _initiate(
        oauth_config=oauth_config, user=user, db_session=db_session
    )

    assert first_state != second_state
    for state, query in ((first_state, first_query), (second_state, second_query)):
        assert query["state"] == [state]
        assert query["code_challenge_method"] == ["S256"]
        assert query["prompt"] == ["consent"]
        assert "code_verifier" not in query

    for code, state in (("second-code", second_state), ("first-code", first_state)):
        result = oauth_config_api.handle_oauth_callback(
            code=code,
            state=state,
            db_session=db_session,
            user=user,
        )
        assert result.redirect_url == "/app?action=17"

    challenges_by_state = {
        first_state: first_query["code_challenge"][0],
        second_state: second_query["code_challenge"][0],
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


def test_flow_omits_pkce_for_provider_without_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oauth_config, user, db_session, token_post = _configure_flow(monkeypatch)
    state, query = _initiate(
        oauth_config=oauth_config, user=user, db_session=db_session
    )

    assert "code_challenge" not in query
    assert "code_challenge_method" not in query

    result = oauth_config_api.handle_oauth_callback(
        code="authorization-code",
        state=state,
        db_session=db_session,
        user=user,
    )

    assert result.redirect_url == "/app?action=17"
    assert "code_verifier" not in token_post.call_args.kwargs["data"]


def test_attempt_is_owner_bound_and_claimed_before_failed_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oauth_config, owner, db_session, token_post = _configure_flow(monkeypatch)
    state, _ = _initiate(oauth_config=oauth_config, user=owner, db_session=db_session)

    with pytest.raises(
        OnyxError, match="Invalid or expired OAuth authorization attempt"
    ):
        oauth_config_api.handle_oauth_callback(
            code="stolen-code",
            state=state,
            db_session=db_session,
            user=_user(),
        )
    token_post.assert_not_called()

    token_post.side_effect = requests.RequestException("provider unavailable")
    oauth_config_api.handle_oauth_callback(
        code="owner-code",
        state=state,
        db_session=db_session,
        user=owner,
    )
    assert token_post.call_count == 1

    with pytest.raises(
        OnyxError, match="Invalid or expired OAuth authorization attempt"
    ):
        oauth_config_api.handle_oauth_callback(
            code="retried-code",
            state=state,
            db_session=db_session,
            user=owner,
        )
    assert token_post.call_count == 1


def test_callback_rejects_configuration_changed_after_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oauth_config, user, db_session, token_post = _configure_flow(monkeypatch)
    state, _ = _initiate(oauth_config=oauth_config, user=user, db_session=db_session)
    oauth_config.supports_pkce = True

    with pytest.raises(
        OnyxError,
        match="OAuth configuration changed while authorization was pending",
    ):
        oauth_config_api.handle_oauth_callback(
            code="authorization-code",
            state=state,
            db_session=db_session,
            user=user,
        )
    token_post.assert_not_called()


def test_initiate_rejects_additional_params_that_override_protocol_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oauth_config, user, db_session, token_post = _configure_flow(monkeypatch)
    oauth_config.additional_params = {
        "state": "admin-state",
        "code_challenge": "admin-challenge",
    }

    with pytest.raises(
        OnyxError,
        match="OAuth additional parameters cannot override: code_challenge, state",
    ):
        _initiate(oauth_config=oauth_config, user=user, db_session=db_session)
    token_post.assert_not_called()


@pytest.mark.parametrize(
    "return_path",
    [
        "https://attacker.example.com",
        "//attacker.example.com",
        "/\\attacker.example.com",
        "/app\nheader",
    ],
)
def test_initiate_request_rejects_unsafe_return_paths(return_path: str) -> None:
    with pytest.raises(ValidationError, match="safe internal path"):
        OAuthInitiateRequest(oauth_config_id=17, return_path=return_path)
