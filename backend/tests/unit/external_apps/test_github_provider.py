"""GitHub provider git-over-HTTPS support: URL claiming and the Basic auth
scheme git endpoints require. Catalog route/policy coverage lives in
``test_github_catalog.py``."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.external_apps import credentials as credentials_mod
from onyx.external_apps.credentials import build_auth_headers
from onyx.external_apps.credentials import resolve_injection_headers
from onyx.external_apps.providers.github import GitHubAction
from onyx.external_apps.providers.github import GitHubProvider
from onyx.external_apps.providers.registry import PROVIDERS
from onyx.sandbox_proxy.request_evaluator import resolve_app_for_url

_CLONE_URLS = [
    "https://github.com/onyx-dot-app/onyx/info/refs?service=git-upload-pack",
    "https://github.com/onyx-dot-app/onyx.git/info/refs?service=git-receive-pack",
    "https://github.com/onyx-dot-app/onyx/git-upload-pack",
    "https://github.com/onyx-dot-app/onyx.git/git-receive-pack",
]

_UNCLAIMED_GITHUB_URLS = [
    "https://github.com/login/oauth/authorize?client_id=x",
    "https://github.com/onyx-dot-app/onyx",  # repo HTML page
    "https://github.com/onyx-dot-app/onyx/releases/download/v1/asset.tgz",
]

_EXPECTED_BASIC = base64.b64encode(b"x-access-token:gho_token123").decode()


def _provider() -> GitHubProvider:
    provider = PROVIDERS[ExternalAppType.GITHUB]
    assert isinstance(provider, GitHubProvider)
    return provider


def _spec_app() -> ExternalApp:
    return ExternalApp(
        app_type=ExternalAppType.GITHUB,
        upstream_url_patterns=list(_provider().spec.descriptor.upstream_url_patterns),
    )


def test_patterns_claim_git_smart_http_only() -> None:
    app = _spec_app()
    for url in _CLONE_URLS:
        assert resolve_app_for_url(url, [app]) is app, url
    for url in _UNCLAIMED_GITHUB_URLS:
        assert resolve_app_for_url(url, [app]) is None, url
    # The API host stays claimed.
    assert resolve_app_for_url("https://api.github.com/user", [app]) is app


def test_git_actions_render_basic_auth() -> None:
    """The git actions' catalog ``auth_template`` + ``derive_credentials``
    together produce the Basic header github.com's git endpoints require."""
    provider = _provider()
    by_action = {e.id: e for e in provider.spec.endpoint_catalog}

    template = by_action[GitHubAction.GIT_READ].auth_template
    assert template is not None
    assert by_action[GitHubAction.GIT_PUSH].auth_template == template

    creds = provider.derive_credentials({"access_token": "gho_token123"})
    assert build_auth_headers(template, creds) == {
        "Authorization": f"Basic {_EXPECTED_BASIC}"
    }


def test_derive_credentials_without_token_is_a_noop() -> None:
    assert _provider().derive_credentials({}) == {}


def test_resolve_injection_headers_selects_template_by_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Git actions render their catalog override (Basic); everything else —
    including no matched actions — renders the app's stored Bearer template."""
    app = MagicMock()
    app.skill.enabled = True
    app.app_type = ExternalAppType.GITHUB
    app.auth_template = {"Authorization": "Bearer {access_token}"}
    app.organization_credentials.get_value.return_value = {
        "access_token": "gho_token123"
    }
    monkeypatch.setattr(credentials_mod, "get_external_app_by_id", lambda *_a: app)
    monkeypatch.setattr(
        credentials_mod,
        "get_external_app_user_credential",
        lambda *_a, **_k: None,
    )

    def _resolve(action_types: list[str] | None) -> dict[str, str]:
        return resolve_injection_headers(
            MagicMock(), 1, uuid4(), action_types=action_types
        )

    assert _resolve([GitHubAction.GIT_READ.value]) == {
        "Authorization": f"Basic {_EXPECTED_BASIC}"
    }
    assert _resolve([GitHubAction.GIT_PUSH.value]) == {
        "Authorization": f"Basic {_EXPECTED_BASIC}"
    }
    assert _resolve([GitHubAction.REPOS_READ.value]) == {
        "Authorization": "Bearer gho_token123"
    }
    assert _resolve(None) == {"Authorization": "Bearer gho_token123"}
