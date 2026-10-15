from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from onyx.auth import oauth_token_manager, permissions
from onyx.auth.pkce import compute_s256_challenge
from onyx.auth.users import current_user
from onyx.db.enums import PermissionAuthority
from onyx.db.models import OAuthConfig, User
from onyx.error_handling.exceptions import OnyxError, register_onyx_exception_handlers
from onyx.server.features.oauth_config import api as oauth_config_api
from onyx.server.features.oauth_config.models import (
    OAuthConfigCreate,
    OAuthConfigUpdate,
    OAuthInitiateRequest,
)
from onyx.utils.sensitive import SensitiveValue, make_mock_sensitive_value
from onyx.utils.url import SSRFException
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
    response = MagicMock(spec=requests.Response, status_code=200)
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

    for store in (
        oauth_config_api._AUTHORIZATION_ATTEMPTS,
        oauth_config_api._TEST_AUTHORIZATION_ATTEMPTS,
    ):
        monkeypatch.setattr(store, "_cache_backend_provider", lambda: cache)
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
    with pytest.raises(OnyxError, match="OAuth token exchange failed"):
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
        match="cannot override.*code_challenge.*state",
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


@pytest.mark.parametrize("credential", ["client_id", "client_secret"])
@pytest.mark.parametrize("value", [None, ""])
def test_cleared_credentials_reject_callback_before_exchange(
    monkeypatch: pytest.MonkeyPatch, credential: str, value: str | None
) -> None:
    oauth_config, user, db_session, token_post = _configure_flow(monkeypatch)
    state, _ = _initiate(oauth_config=oauth_config, user=user, db_session=db_session)
    monkeypatch.setattr(oauth_config, credential, value)

    with pytest.raises(OnyxError, match="configuration changed"):
        oauth_config_api.handle_oauth_callback(
            code="authorization-code", state=state, db_session=db_session, user=user
        )
    token_post.assert_not_called()
    with pytest.raises(OnyxError, match="Invalid or expired"):
        oauth_config_api.handle_oauth_callback(
            code="authorization-code", state=state, db_session=db_session, user=user
        )


def test_action_resource_parameter_remains_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oauth_config, user, db_session, token_post = _configure_flow(monkeypatch)
    oauth_config.additional_params = {"resource": "https://resource.example.com"}
    state, query = _initiate(
        oauth_config=oauth_config, user=user, db_session=db_session
    )
    assert query["resource"] == ["https://resource.example.com"]
    result = oauth_config_api.handle_oauth_callback(
        code="authorization-code", state=state, db_session=db_session, user=user
    )
    assert result.redirect_url == "/app?action=17"
    assert token_post.call_count == 1


@pytest.mark.parametrize("operation", ["create", "update", "initiate"])
@pytest.mark.parametrize("query_override", [False, True])
def test_invalid_authorization_configuration_is_rejected_before_storage(
    monkeypatch: pytest.MonkeyPatch, operation: str, query_override: bool
) -> None:
    oauth_config, user, db_session, token_post = _configure_flow(monkeypatch)
    authorization_url = oauth_config.authorization_url
    additional_params = None
    if query_override:
        authorization_url += "?state=overridden-state"
    else:
        additional_params = {"state": "overridden-state"}
    create_config = MagicMock()
    update_config = MagicMock()
    monkeypatch.setattr(oauth_config_api, "create_oauth_config", create_config)
    monkeypatch.setattr(oauth_config_api, "update_oauth_config", update_config)
    monkeypatch.setattr(oauth_config_api, "has_global_permission", lambda *_: True)
    monkeypatch.setattr(
        oauth_config_api, "validate_oauth_endpoint_url", lambda *_args, **_kwargs: None
    )

    with pytest.raises(OnyxError, match="cannot override.*state"):
        if operation == "create":
            oauth_config_api.create_oauth_config_endpoint(
                OAuthConfigCreate(
                    name="OAuth",
                    authorization_url=authorization_url,
                    token_url=oauth_config.token_url,
                    client_id="client-id",
                    client_secret="secret",
                    additional_params=additional_params,
                ),
                db_session=db_session,
                _=user,
            )
        elif operation == "update":
            oauth_config_api.update_oauth_config_endpoint(
                oauth_config.id,
                OAuthConfigUpdate(
                    authorization_url=authorization_url,
                    additional_params=additional_params,
                ),
                db_session=db_session,
                user=user,
            )
        else:
            oauth_config.authorization_url = authorization_url
            oauth_config.additional_params = additional_params
            _initiate(oauth_config=oauth_config, user=user, db_session=db_session)
    create_config.assert_not_called()
    update_config.assert_not_called()
    token_post.assert_not_called()


def test_persistence_failure_is_not_reported_as_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oauth_config, user, db_session, _ = _configure_flow(monkeypatch)
    state, _ = _initiate(oauth_config=oauth_config, user=user, db_session=db_session)
    monkeypatch.setattr(
        oauth_config_api,
        "upsert_user_oauth_token",
        MagicMock(side_effect=RuntimeError("database unavailable")),
    )
    with pytest.raises(RuntimeError, match="database unavailable"):
        oauth_config_api.handle_oauth_callback(
            code="authorization-code", state=state, db_session=db_session, user=user
        )


@pytest.mark.parametrize("invalid_endpoint", [False, True])
def test_provider_failure_returns_http_error_and_consumes_attempt(
    monkeypatch: pytest.MonkeyPatch,
    invalid_endpoint: bool,
) -> None:
    oauth_config, user, db_session, token_post = _configure_flow(monkeypatch)
    monkeypatch.setattr(
        permissions, "has_permission", lambda *_: PermissionAuthority.GLOBAL
    )
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.include_router(oauth_config_api.router)
    app.dependency_overrides[oauth_config_api.get_session] = lambda: db_session
    app.dependency_overrides[current_user] = lambda: user
    if invalid_endpoint:
        monkeypatch.setattr(
            oauth_token_manager,
            "validate_oauth_endpoint_url",
            MagicMock(side_effect=SSRFException("private endpoint secret")),
        )
    else:
        token_post.side_effect = requests.HTTPError("provider body contains secret")
    with TestClient(app) as client:
        started = client.post(
            "/oauth-config/initiate", json={"oauth_config_id": oauth_config.id}
        )
        assert started.status_code == 200
        params = {"state": started.json()["state"], "code": "authorization-code"}
        failed = client.post("/oauth-config/callback", params=params)
        assert failed.status_code == 502
        assert failed.json()["error_code"] == "BAD_GATEWAY"
        assert "secret" not in failed.text
        replay = client.post("/oauth-config/callback", params=params)
        assert replay.status_code == 400
    assert token_post.call_count == (0 if invalid_endpoint else 1)


# Draft connection tests must not mutate production credentials.


@pytest.mark.parametrize("pkce", [False, True])
def test_draft_connection_exchanges_code_without_saving(
    monkeypatch: pytest.MonkeyPatch, pkce: bool
) -> None:
    from onyx.server.features.oauth_config.models import OAuthTestInitiateRequest

    _, user, db, token_post = _configure_flow(monkeypatch)
    monkeypatch.setattr(
        oauth_config_api, "validate_oauth_endpoint_url", lambda *_a, **_kw: None
    )
    writes = MagicMock()
    monkeypatch.setattr(oauth_config_api, "upsert_user_oauth_token", writes)
    started = oauth_config_api.initiate_oauth_test(
        OAuthTestInitiateRequest(
            authorization_url="https://draft.example.com/authorize",
            token_url="https://draft.example.com/token",
            client_id="draft-client",
            client_secret="draft-secret",
            scopes=["read"],
            supports_pkce=pkce,
        ),
        db_session=db,
        user=user,
    )
    query = parse_qs(urlparse(started.authorization_url).query)
    assert query["redirect_uri"] == [oauth_config_api._OAUTH_CALLBACK_URL]
    assert "draft-secret" not in started.model_dump_json()
    assert ("code_challenge" in query) is pkce
    result = oauth_config_api.complete_oauth_test(
        code="test-code",
        state=started.state,
        db_session=db,
        user=user,
    )
    assert result.supports_pkce is pkce
    body = token_post.call_args.kwargs["data"]
    assert token_post.call_args.args == ("https://draft.example.com/token",)
    assert body["client_id"] == "draft-client"
    assert body["client_secret"] == "draft-secret"
    if pkce:
        assert (
            compute_s256_challenge(body["code_verifier"]) == query["code_challenge"][0]
        )
    else:
        assert "code_verifier" not in body
    writes.assert_not_called()
    db.commit.assert_not_called()
    with pytest.raises(OnyxError, match="Invalid or expired"):
        oauth_config_api.complete_oauth_test(
            code="test-code", state=started.state, db_session=db, user=user
        )
    assert token_post.call_count == 1


@pytest.mark.parametrize("repair_credentials", [False, True])
def test_draft_can_reuse_or_repair_saved_credentials_without_updating_them(
    monkeypatch: pytest.MonkeyPatch, repair_credentials: bool
) -> None:
    from onyx.server.features.oauth_config.models import OAuthTestInitiateRequest

    config, user, db, token_post = _configure_flow(monkeypatch)
    monkeypatch.setattr(
        oauth_config_api, "validate_oauth_endpoint_url", lambda *_a, **_kw: None
    )
    monkeypatch.setattr(oauth_config_api, "has_global_permission", lambda *_a: True)
    if repair_credentials:
        config.client_id = None
        config.client_secret = None
    original = (config.client_id, config.client_secret, config.authorization_url)
    started = oauth_config_api.initiate_oauth_test(
        OAuthTestInitiateRequest(
            oauth_config_id=config.id,
            authorization_url="https://draft.example.com/authorize",
            token_url="https://draft.example.com/token",
            client_id="replacement-id" if repair_credentials else None,
            client_secret="replacement-secret" if repair_credentials else None,
        ),
        db_session=db,
        user=user,
    )
    assert parse_qs(urlparse(started.authorization_url).query)["prompt"] == ["consent"]
    oauth_config_api.complete_oauth_test(
        code="test-code", state=started.state, db_session=db, user=user
    )
    body = token_post.call_args.kwargs["data"]
    assert body["client_id"] == (
        "replacement-id" if repair_credentials else "client-id"
    )
    assert body["client_secret"] == (
        "replacement-secret" if repair_credentials else "client-secret"
    )
    assert (
        config.client_id,
        config.client_secret,
        config.authorization_url,
    ) == original
    db.commit.assert_not_called()


@pytest.mark.parametrize("reuse_saved_secret", [False, True])
def test_draft_pkce_preserves_explicit_empty_client_secret(
    monkeypatch: pytest.MonkeyPatch, reuse_saved_secret: bool
) -> None:
    from onyx.server.features.oauth_config.models import OAuthTestInitiateRequest

    config, user, db, token_post = _configure_flow(monkeypatch)
    config.client_secret = make_mock_sensitive_value("")
    config.supports_pkce = True
    monkeypatch.setattr(
        oauth_config_api, "validate_oauth_endpoint_url", lambda *_a, **_kw: None
    )
    monkeypatch.setattr(oauth_config_api, "has_global_permission", lambda *_a: True)
    writes = MagicMock()
    monkeypatch.setattr(oauth_config_api, "upsert_user_oauth_token", writes)
    started = oauth_config_api.initiate_oauth_test(
        OAuthTestInitiateRequest(
            oauth_config_id=config.id if reuse_saved_secret else None,
            authorization_url=config.authorization_url,
            token_url=config.token_url,
            client_id=None if reuse_saved_secret else "public-client",
            client_secret=None if reuse_saved_secret else "",
            supports_pkce=True,
        ),
        db_session=db,
        user=user,
    )
    query = parse_qs(urlparse(started.authorization_url).query)
    result = oauth_config_api.complete_oauth_test(
        code="test-code", state=started.state, db_session=db, user=user
    )
    assert result.supports_pkce
    body = token_post.call_args.kwargs["data"]
    assert "client_secret" not in body
    assert body["client_id"] == ("client-id" if reuse_saved_secret else "public-client")
    assert compute_s256_challenge(body["code_verifier"]) == query["code_challenge"][0]
    assert config.client_secret is not None
    assert config.client_secret.get_value(apply_mask=False) == ""
    writes.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.parametrize("change", ["owner", "config", "deleted", "permissions"])
def test_draft_callback_rejects_invalid_owner_or_changed_config(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    from onyx.server.features.oauth_config.models import OAuthTestInitiateRequest

    config, user, db, token_post = _configure_flow(monkeypatch)
    monkeypatch.setattr(
        oauth_config_api, "validate_oauth_endpoint_url", lambda *_a, **_kw: None
    )
    monkeypatch.setattr(oauth_config_api, "has_global_permission", lambda *_a: True)
    started = oauth_config_api.initiate_oauth_test(
        OAuthTestInitiateRequest(
            oauth_config_id=config.id,
            authorization_url=config.authorization_url,
            token_url=config.token_url,
        ),
        db_session=db,
        user=user,
    )
    if change == "owner":
        user = _user()
    elif change == "config":
        config.client_secret = make_mock_sensitive_value("rotated-secret")
    elif change == "deleted":
        monkeypatch.setattr(oauth_config_api, "get_oauth_config", lambda *_a: None)
    else:
        monkeypatch.setattr(
            oauth_config_api, "has_global_permission", lambda *_a: False
        )
        monkeypatch.setattr(
            oauth_config_api, "get_tools_by_oauth_config", lambda *_a: []
        )
    with pytest.raises(OnyxError):
        oauth_config_api.complete_oauth_test(
            code="test-code", state=started.state, db_session=db, user=user
        )
    token_post.assert_not_called()


def test_draft_cannot_read_another_owners_saved_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.server.features.oauth_config.models import OAuthTestInitiateRequest

    config, user, db, token_post = _configure_flow(monkeypatch)
    monkeypatch.setattr(
        oauth_config_api, "validate_oauth_endpoint_url", lambda *_a, **_kw: None
    )
    monkeypatch.setattr(oauth_config_api, "has_global_permission", lambda *_a: False)
    monkeypatch.setattr(
        oauth_config_api,
        "get_tools_by_oauth_config",
        lambda *_a: [SimpleNamespace(user_id=uuid4())],
    )
    with pytest.raises(OnyxError, match="only manage"):
        oauth_config_api.initiate_oauth_test(
            OAuthTestInitiateRequest(
                oauth_config_id=config.id,
                authorization_url=config.authorization_url,
                token_url=config.token_url,
            ),
            db_session=db,
            user=user,
        )
    token_post.assert_not_called()


def test_draft_state_cannot_be_used_in_normal_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.server.features.oauth_config.models import OAuthTestInitiateRequest

    config, user, db, token_post = _configure_flow(monkeypatch)
    monkeypatch.setattr(
        oauth_config_api, "validate_oauth_endpoint_url", lambda *_a, **_kw: None
    )
    started = oauth_config_api.initiate_oauth_test(
        OAuthTestInitiateRequest(
            authorization_url=config.authorization_url,
            token_url=config.token_url,
            client_id="draft",
            client_secret="draft",
        ),
        db_session=db,
        user=user,
    )
    with pytest.raises(OnyxError, match="Invalid or expired"):
        oauth_config_api.handle_oauth_callback(
            code="test-code", state=started.state, db_session=db, user=user
        )
    token_post.assert_not_called()
    oauth_config_api.complete_oauth_test(
        code="test-code", state=started.state, db_session=db, user=user
    )
    assert token_post.call_count == 1


@pytest.mark.parametrize("authorized", [False, True])
def test_draft_http_permission_and_provider_error_contract(
    monkeypatch: pytest.MonkeyPatch, authorized: bool
) -> None:
    from onyx.db.enums import Permission

    config, user, db, token_post = _configure_flow(monkeypatch)
    monkeypatch.setattr(
        oauth_config_api, "validate_oauth_endpoint_url", lambda *_a, **_kw: None
    )
    monkeypatch.setattr(
        permissions,
        "has_permission",
        lambda _user, permission: (
            PermissionAuthority.GLOBAL
            if authorized or permission == Permission.BASIC_ACCESS
            else PermissionAuthority.NONE
        ),
    )
    token_post.side_effect = requests.HTTPError("provider body contains secret")
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.include_router(oauth_config_api.admin_router)
    app.dependency_overrides[oauth_config_api.get_session] = lambda: db
    app.dependency_overrides[current_user] = lambda: user
    with TestClient(app) as client:
        started = client.post(
            "/admin/oauth-config/test/initiate",
            json={
                "authorization_url": config.authorization_url,
                "token_url": config.token_url,
                "client_id": "draft",
                "client_secret": "draft",
            },
        )
        if not authorized:
            assert started.status_code == 403
            discovery = client.post(
                "/admin/oauth-config/pkce-support",
                json={
                    "authorization_url": config.authorization_url,
                    "token_url": config.token_url,
                },
            )
            assert discovery.status_code == 403
            callback = client.post(
                "/admin/oauth-config/test/callback",
                params={"code": "code", "state": "state"},
            )
            assert callback.status_code == 403
            token_post.assert_not_called()
            return
        assert started.status_code == 200
        params = {"code": "test-code", "state": started.json()["state"]}
        failed = client.post("/admin/oauth-config/test/callback", params=params)
        assert failed.status_code == 502
        assert "secret" not in failed.text
        assert (
            client.post("/admin/oauth-config/test/callback", params=params).status_code
            == 400
        )
    assert token_post.call_count == 1
    db.commit.assert_not_called()


@pytest.mark.parametrize("empty_field", ["client_id", "client_secret"])
def test_snapshot_reports_cleared_encrypted_credentials(
    monkeypatch: pytest.MonkeyPatch, empty_field: str
) -> None:
    config = _oauth_config()
    config.name = "Provider"
    config.created_at = config.updated_at = datetime.now(timezone.utc)
    config.client_id = SensitiveValue[str](
        encrypted_bytes=b"id",
        decrypt_fn=lambda _: "" if empty_field == "client_id" else "client-id",
    )
    config.client_secret = SensitiveValue[str](
        encrypted_bytes=b"secret",
        decrypt_fn=lambda _: "" if empty_field == "client_secret" else "client-secret",
    )
    monkeypatch.setattr(oauth_config_api, "get_tools_by_oauth_config", lambda *_: [])
    snapshot = oauth_config_api._oauth_config_to_snapshot(
        config, MagicMock(spec=Session)
    )
    assert snapshot.has_client_credentials is False
