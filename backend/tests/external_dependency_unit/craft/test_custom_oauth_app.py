"""Custom apps with an admin-defined OAuth flow: the API-level glue the unit
tests can't see — persistence + echo of ``oauth_config``, PATCH's unset-vs-null
semantics, the user-facing ``auth_flow``, and the start → callback exchange
against a mocked token endpoint."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any
from urllib.parse import parse_qs
from urllib.parse import urlparse
from uuid import uuid4

import pytest
import requests
from fastapi import UploadFile
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.orm import Session

import onyx.server.features.build.api.external_apps_api as api
import onyx.server.features.build.api.external_apps_oauth_api as oauth_api
from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.db.models import ExternalAppUserCredential
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.custom_oauth import CustomOAuthConfig
from onyx.server.features.build.api.models import ExternalAppAdminResponse
from onyx.server.features.build.api.models import OAuthCallbackRequest
from onyx.server.features.build.api.models import UpdateExternalAppRequest

_UPSTREAM = ["https://api.example.com/*"]
_OAUTH_TEMPLATE = {"Authorization": "Bearer {access_token}"}
_OAUTH_CONFIG: dict[str, Any] = {
    "authorize_url": "https://idp.example.com/oauth/authorize",
    "token_url": "https://idp.example.com/oauth/token",
    "scope": "read write",
}


def _noop(*_args: object, **_kwargs: object) -> None:
    return None


def _bundle_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "SKILL.md",
            "---\nname: Bundle Name\ndescription: Bundle description\n---\n\nDo things.\n",
        )
    return buf.getvalue()


def _create_oauth_app(
    db_session: Session,
    test_user: User,
    slug: str,
    *,
    auth_template: dict[str, str] = _OAUTH_TEMPLATE,
    oauth_config: dict[str, Any] | None = _OAUTH_CONFIG,
) -> ExternalAppAdminResponse:
    return api.create_custom_external_app(
        name="OAuth Custom App",
        description="",
        upstream_url_patterns=json.dumps(_UPSTREAM),
        auth_template=json.dumps(auth_template),
        organization_credentials=json.dumps(
            {"client_id": "cid", "client_secret": "shh"}
        ),
        enabled=True,
        oauth_config=json.dumps(oauth_config) if oauth_config is not None else None,
        bundle=UploadFile(file=io.BytesIO(_bundle_zip()), filename=f"{slug}.zip"),
        _=test_user,
        db_session=db_session,
    )


def _cleanup(db_session: Session, slug: str) -> None:
    db_session.execute(delete(Skill).where(Skill.slug == slug))
    db_session.commit()


def _user_view(db_session: Session, test_user: User, app_id: int) -> Any:
    apps = api.list_external_apps(user=test_user, db_session=db_session)
    return next(a for a in apps if a.id == app_id)


@pytest.fixture(autouse=True, scope="module")
def _ensure_bundle_store(initialize_file_store: None) -> None:  # noqa: ARG001
    """Create the bundle blob store before any test runs."""


def test_create_persists_and_echoes_oauth_config(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api, "push_skill_to_affected_sandboxes", _noop)
    slug = f"custom-oauth-{uuid4().hex[:8]}"

    resp = _create_oauth_app(db_session, test_user, slug)

    assert resp.oauth_config is not None
    assert resp.oauth_config.authorize_url == _OAUTH_CONFIG["authorize_url"]
    assert resp.oauth_config.token_url == _OAUTH_CONFIG["token_url"]
    assert resp.oauth_config.scope == "read write"
    # Defaults materialized server-side.
    assert resp.oauth_config.scope_param == "scope"
    assert resp.oauth_config.token_endpoint_auth_method == "client_secret_post"

    app = db_session.scalar(select(ExternalApp).where(ExternalApp.id == resp.id))
    assert app is not None
    assert app.oauth_config is not None
    assert app.oauth_config["token_url"] == _OAUTH_CONFIG["token_url"]

    # The user view dispatches this app to the OAuth connect flow.
    user_view = _user_view(db_session, test_user, resp.id)
    assert user_view.auth_flow == "oauth"
    assert user_view.authenticated is False  # no token stored yet

    _cleanup(db_session, slug)


def test_create_oauth_requires_access_token_in_template(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api, "push_skill_to_affected_sandboxes", _noop)
    slug = f"custom-oauth-{uuid4().hex[:8]}"

    with pytest.raises(OnyxError):
        _create_oauth_app(
            db_session,
            test_user,
            slug,
            auth_template={"Authorization": "Bearer {api_key}"},
        )
    assert db_session.scalar(select(Skill).where(Skill.slug == slug)) is None


def test_static_custom_app_reads_as_manual(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api, "push_skill_to_affected_sandboxes", _noop)
    slug = f"custom-oauth-{uuid4().hex[:8]}"

    resp = _create_oauth_app(
        db_session,
        test_user,
        slug,
        auth_template={"Authorization": "Bearer {api_key}"},
        oauth_config=None,
    )
    assert resp.oauth_config is None
    assert _user_view(db_session, test_user, resp.id).auth_flow == "manual"

    _cleanup(db_session, slug)


def test_patch_unset_leaves_config_and_null_clears_it(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api, "push_skill_to_affected_sandboxes", _noop)
    slug = f"custom-oauth-{uuid4().hex[:8]}"
    created = _create_oauth_app(db_session, test_user, slug)

    # oauth_config omitted from the request → untouched.
    edited = api.update_external_app_admin(
        external_app_id=created.id,
        request=UpdateExternalAppRequest(name="Renamed"),
        _=test_user,
        db_session=db_session,
    )
    assert edited.name == "Renamed"
    assert edited.oauth_config is not None

    # Explicit null → cleared back to manual credentials. The OAuth-mode
    # template constraint no longer applies, so the template can change too.
    cleared = api.update_external_app_admin(
        external_app_id=created.id,
        request=UpdateExternalAppRequest(
            oauth_config=None,
            auth_template={"Authorization": "Bearer {api_key}"},
        ),
        _=test_user,
        db_session=db_session,
    )
    assert cleared.oauth_config is None
    assert _user_view(db_session, test_user, created.id).auth_flow == "manual"

    _cleanup(db_session, slug)


def test_patch_oauth_validates_effective_template(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An app that has (or is being given) an OAuth config rejects a template
    edit that the flow could never fill."""
    monkeypatch.setattr(api, "push_skill_to_affected_sandboxes", _noop)
    slug = f"custom-oauth-{uuid4().hex[:8]}"
    created = _create_oauth_app(db_session, test_user, slug)

    with pytest.raises(OnyxError):
        api.update_external_app_admin(
            external_app_id=created.id,
            request=UpdateExternalAppRequest(
                auth_template={"Authorization": "Bearer {api_key}"}
            ),
            _=test_user,
            db_session=db_session,
        )

    _cleanup(db_session, slug)


def test_patch_rejects_oauth_config_on_built_in(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.server.features.build.api.models import CreateBuiltInExternalAppRequest

    monkeypatch.setattr(api, "push_skill_to_affected_sandboxes", _noop)
    created = api.create_built_in_external_app(
        request=CreateBuiltInExternalAppRequest(
            name="Slack",
            description="",
            enabled=True,
            app_type=ExternalAppType.SLACK,
            upstream_url_patterns=["https://slack\\.com/api/.*"],
            auth_template={"Authorization": "Bearer {access_token}"},
            organization_credentials={},
        ),
        _=test_user,
        db_session=db_session,
    )
    try:
        with pytest.raises(OnyxError):
            api.update_external_app_admin(
                external_app_id=created.id,
                request=UpdateExternalAppRequest(
                    oauth_config=CustomOAuthConfig.model_validate(_OAUTH_CONFIG),
                ),
                _=test_user,
                db_session=db_session,
            )
        # An explicit null is a no-op, not an error: full-body clients (e.g.
        # the integration ExternalAppManager) send `oauth_config: null`.
        edited = api.update_external_app_admin(
            external_app_id=created.id,
            request=UpdateExternalAppRequest(name="Slack 2", oauth_config=None),
            _=test_user,
            db_session=db_session,
        )
        assert edited.name == "Slack 2"
        assert edited.oauth_config is None
    finally:
        app = db_session.scalar(select(ExternalApp).where(ExternalApp.id == created.id))
        assert app is not None
        _cleanup(db_session, app.skill.slug)


def test_oauth_start_and_callback_round_trip(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The full user connect flow against a mocked token endpoint: /start
    builds the authorize URL from the stored config, /callback exchanges the
    code via the config-driven handler and persists stamped credentials, and
    the state is one-shot."""
    monkeypatch.setattr(api, "push_skill_to_affected_sandboxes", _noop)
    slug = f"custom-oauth-{uuid4().hex[:8]}"
    created = _create_oauth_app(db_session, test_user, slug)

    start = oauth_api.start_external_app_oauth(
        external_app_id=created.id, user=test_user, db_session=db_session
    )
    assert start.authorize_url.startswith("https://idp.example.com/oauth/authorize?")
    params = parse_qs(urlparse(start.authorize_url).query)
    assert params["client_id"] == ["cid"]
    assert params["scope"] == ["read write"]
    assert params["response_type"] == ["code"]
    # The served (displayed) redirect URI must be exactly what the flow sends.
    displayed = oauth_api.get_oauth_redirect_uri(_=test_user)
    assert params["redirect_uri"] == [displayed.redirect_uri]
    state = params["state"][0]

    captured: dict[str, Any] = {}

    def _post(url: str, **kwargs: Any) -> requests.Response:
        captured["url"] = url
        captured["data"] = kwargs.get("data")
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(
            {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600}
        ).encode()
        return response

    monkeypatch.setattr("onyx.external_apps.oauth_handler.requests.post", _post)

    result = oauth_api.handle_external_app_oauth_callback(
        request=OAuthCallbackRequest(code="c0de", state=state),
        user=test_user,
        db_session=db_session,
    )
    assert result.success is True
    assert captured["url"] == _OAUTH_CONFIG["token_url"]
    assert captured["data"]["grant_type"] == "authorization_code"
    assert captured["data"]["code"] == "c0de"
    assert captured["data"]["client_secret"] == "shh"

    cred = db_session.scalar(
        select(ExternalAppUserCredential).where(
            ExternalAppUserCredential.external_app_id == created.id,
            ExternalAppUserCredential.user_id == test_user.id,
        )
    )
    assert cred is not None
    stored = cred.user_credentials.get_value(apply_mask=False)
    assert stored["access_token"] == "at-1"
    assert stored["refresh_token"] == "rt-1"
    assert "expires_at" in stored  # stamped from expires_in

    # The OAuth flow satisfied the template's per-user gap.
    assert _user_view(db_session, test_user, created.id).authenticated is True

    # State is one-shot — a replayed callback is rejected.
    with pytest.raises(OnyxError):
        oauth_api.handle_external_app_oauth_callback(
            request=OAuthCallbackRequest(code="c0de", state=state),
            user=test_user,
            db_session=db_session,
        )

    _cleanup(db_session, slug)
