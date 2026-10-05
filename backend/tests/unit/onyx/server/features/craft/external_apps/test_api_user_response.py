from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp, ExternalAppUserCredential
from onyx.server.features.build.external_apps.api import _to_user_response
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
    oauth_config: dict[str, Any] | None = None,
) -> ExternalApp:
    return cast(
        ExternalApp,
        SimpleNamespace(
            id=1,
            name="Test App",
            app_type=app_type,
            auth_template=auth_template,
            organization_credentials=_sensitive_dict(organization_credentials),
            oauth_config=oauth_config,
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


def test_user_response_supports_oauth_for_custom_app_with_oauth_config() -> None:
    org = {"client_id": "cid", "client_secret": "sec"}
    template = {"Authorization": "Bearer {access_token}"}
    oauth_config = {
        "authorize_url": "https://auth.example.com/authorize",
        "token_url": "https://auth.example.com/token",
        "scopes": ["read"],
    }
    static_app = _external_app(auth_template=template, organization_credentials=org)
    oauth_app = _external_app(
        auth_template=template,
        organization_credentials=org,
        oauth_config=oauth_config,
    )

    assert _to_user_response(static_app, None).supports_oauth is False
    response = _to_user_response(oauth_app, None)
    assert response.supports_oauth is True
    # The OAuth flow fills `access_token`; until then the user isn't connected.
    assert response.credential_keys == ["access_token"]
    assert response.authenticated is False
