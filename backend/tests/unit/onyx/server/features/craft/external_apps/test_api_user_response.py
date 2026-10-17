from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest

from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp, ExternalAppUserCredential
from onyx.server.features.build.external_apps.api import _to_user_response
from onyx.server.features.build.external_apps.models import ExternalAppUserResponse
from onyx.utils.encryption import mask_string
from onyx.utils.sensitive import SensitiveValue


def _sensitive_dict(value: dict[str, Any]) -> SensitiveValue[dict[str, Any]]:
    return SensitiveValue(
        encrypted_bytes=json.dumps(value).encode(),
        decrypt_fn=lambda value_bytes: value_bytes.decode(),
        is_json=True,
    )


def _external_app(
    *,
    auth_template: dict[str, Any],
    organization_credentials: dict[str, Any],
    app_type: ExternalAppType = ExternalAppType.CUSTOM,
    upstream_url_patterns: list[str] | None = None,
) -> ExternalApp:
    return cast(
        ExternalApp,
        SimpleNamespace(
            id=1,
            name="Test App",
            app_type=app_type,
            auth_template=auth_template,
            organization_credentials=_sensitive_dict(organization_credentials),
            upstream_url_patterns=upstream_url_patterns or [],
        ),
    )


def _user_credential(
    user_credentials: dict[str, Any],
) -> ExternalAppUserCredential:
    return cast(
        ExternalAppUserCredential,
        SimpleNamespace(user_credentials=_sensitive_dict(user_credentials)),
    )


def test_user_response_masks_stored_user_credentials() -> None:
    app = _external_app(
        auth_template={
            "Authorization": "Bearer {access_token}",
            "X-Refresh": "{refresh_token}",
            "X-Cloud": "{cloud_id}",
            "X-Client": "{client_id}",
        },
        organization_credentials={"client_id": "org-client-id"},
    )
    user_credentials = {
        "access_token": "USER_ACCESS_TOKEN",
        "cloud_id": "cloud-id-should-still-mask",
        "refresh_token": "USER_REFRESH_TOKEN",
    }

    response = _to_user_response(app, _user_credential(user_credentials))

    assert response.authenticated is True
    assert response.credential_keys == ["access_token", "cloud_id", "refresh_token"]
    assert response.credential_values == {
        key: mask_string(value) for key, value in user_credentials.items()
    }
    assert "USER_ACCESS_TOKEN" not in response.credential_values.values()
    assert "cloud-id-should-still-mask" not in response.credential_values.values()
    assert "USER_REFRESH_TOKEN" not in response.credential_values.values()


def test_user_response_masks_built_in_oauth_bearer_token() -> None:
    app = _external_app(
        app_type=ExternalAppType.SLACK,
        auth_template={"Authorization": "Bearer {access_token}"},
        organization_credentials={},
    )
    user_credentials = {
        "access_token": "xoxp-raw-oauth-access-token",
        "refresh_token": "unused-refresh-token",
    }

    response = _to_user_response(app, _user_credential(user_credentials))

    assert response.authenticated is True
    assert response.credential_keys == ["access_token"]
    assert response.credential_values == {
        "access_token": mask_string(user_credentials["access_token"])
    }
    assert (
        response.credential_values["access_token"] != user_credentials["access_token"]
    )
    assert "refresh_token" not in response.credential_values


def test_user_response_uses_raw_presence_for_authentication() -> None:
    app = _external_app(
        auth_template={
            "Authorization": "Bearer {access_token}",
            "X-Refresh": "{refresh_token}",
        },
        organization_credentials={},
    )

    response = _to_user_response(
        app, _user_credential({"access_token": "USER_ACCESS_TOKEN"})
    )

    assert response.authenticated is False
    assert response.credential_values == {
        "access_token": mask_string("USER_ACCESS_TOKEN")
    }


@pytest.mark.parametrize(
    ("app_type", "patterns", "origins"),
    [
        (
            ExternalAppType.LINEAR,
            [r"https://api\.linear\.app/.*"],
            ["https://api.linear.app"],
        ),
        (
            ExternalAppType.CUSTOM,
            ["https://api.linear.app/*"],
            ["https://api.linear.app"],
        ),
        (
            ExternalAppType.CUSTOM,
            ["https://user:secret@API.Example.com:443/private?token=secret#fragment"],
            ["https://api.example.com"],
        ),
        (
            ExternalAppType.CUSTOM,
            ["https://api.example.com?token=secret", "https://api.example.com:8443/*"],
            ["https://api.example.com", "https://api.example.com:8443"],
        ),
        (
            ExternalAppType.CUSTOM,
            [
                "http://API.Example.com:80/a",
                "http://api.example.com/*",
                "https://api.example.com:443/*",
            ],
            ["http://api.example.com", "https://api.example.com"],
        ),
        (
            ExternalAppType.LINEAR,
            [
                r"https://(?:api|www)\.linear\.app/.*",
                r"https://api\.linear\.app?/.*",
                r"https://.*\.linear\.app/.*",
            ],
            [],
        ),
        (
            ExternalAppType.CUSTOM,
            [
                "https://*.example.com/*",
                "https://api.example.com:bad/*",
                "ftp://api.example.com/*",
                "https://api%2eexample.com/*",
                "https://api?.example.com/*",
                "https://api\n.example.com/*",
            ],
            [],
        ),
        (
            ExternalAppType.CUSTOM,
            ["https://[2001:db8::1]:443/*"],
            ["https://[2001:db8::1]"],
        ),
    ],
)
def test_user_response_projects_only_clean_service_origins(
    app_type: ExternalAppType, patterns: list[str], origins: list[str]
) -> None:
    app = _external_app(
        auth_template={},
        organization_credentials={"client_secret": "org-secret"},
        app_type=app_type,
        upstream_url_patterns=patterns,
    )

    response = _to_user_response(app, None).model_dump()

    assert response["service_urls"] == origins
    assert set(response) == {
        "id",
        "name",
        "app_type",
        "credential_keys",
        "credential_values",
        "authenticated",
        "supports_oauth",
        "service_urls",
    }
    assert "org-secret" not in json.dumps(response)


def test_user_response_service_origins_default_to_empty() -> None:
    response = ExternalAppUserResponse(
        id=1,
        name="Test App",
        app_type=ExternalAppType.CUSTOM,
        credential_keys=[],
        credential_values={},
        authenticated=True,
        supports_oauth=False,
    )

    assert response.service_urls == []
