from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from typing import cast

from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.db.models import ExternalAppUserCredential
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
) -> ExternalApp:
    return cast(
        ExternalApp,
        SimpleNamespace(
            id=1,
            skill=SimpleNamespace(
                name="Test App",
                description="Test description",
                slug="test-app",
            ),
            app_type=app_type,
            auth_template=auth_template,
            organization_credentials=_sensitive_dict(organization_credentials),
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
