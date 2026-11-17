from __future__ import annotations

import json
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType, IntegrationAuthMethod, IntegrationAuthMode
from onyx.db.models import ExternalApp, Integration, User
from onyx.integrations.connection_models import ConnectionSecret, ConnectionState
from onyx.server.features.build.external_apps import api
from onyx.server.features.build.external_apps.api import _to_user_response
from onyx.server.features.build.external_apps.models import ExternalAppUserResponse
from onyx.utils.encryption import mask_string

_USER = cast(User, SimpleNamespace(id="user-id"))
_DB = cast(Session, None)


def _external_app(
    *,
    app_type: ExternalAppType = ExternalAppType.CUSTOM,
    upstream_url_patterns: list[str] | None = None,
) -> ExternalApp:
    return cast(
        ExternalApp,
        SimpleNamespace(
            id=1,
            name="Old copy",
            app_type=app_type,
            upstream_url_patterns=upstream_url_patterns or [],
        ),
    )


def _integration(
    *,
    auth_method: IntegrationAuthMethod | None = IntegrationAuthMethod.API_KEY,
    auth_mode: IntegrationAuthMode = IntegrationAuthMode.INDIVIDUAL,
    header_template: dict[str, str] | None = None,
) -> Integration:
    return cast(
        Integration,
        SimpleNamespace(
            id=7,
            name="Test App",
            auth_method=auth_method,
            auth_mode=auth_mode,
            credential_fields=None,
            header_template=header_template or {},
        ),
    )


@pytest.fixture
def connection(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """The user's saved fields and the state that ``integration_status``
    gives."""
    stored: dict[str, object] = {"fields": {}, "state": ConnectionState.CONNECTED}
    monkeypatch.setattr(api, "get_connection", lambda *_: object())
    monkeypatch.setattr(
        api,
        "read_connection_secret",
        lambda _: ConnectionSecret(fields=cast(dict[str, str], stored["fields"])),
    )
    monkeypatch.setattr(
        api,
        "integration_status",
        lambda *_: SimpleNamespace(state=stored["state"]),
    )
    return stored


def test_user_response_masks_saved_fields(connection: dict[str, object]) -> None:
    connection["fields"] = {
        "api_key": "USER_API_KEY",
        "cloud_id": "cloud-id-should-still-mask",
        "stale": "not-in-the-template",
    }
    integration = _integration(
        header_template={
            "Authorization": "Bearer {api_key}",
            "X-Cloud": "{cloud_id}",
            "X-User": "{user_email}",
        }
    )

    response = _to_user_response(_external_app(), integration, _USER, _DB)

    assert response.name == "Test App"
    assert response.authenticated is True
    assert response.credential_keys == ["api_key", "cloud_id"]
    assert response.credential_values == {
        "api_key": mask_string("USER_API_KEY"),
        "cloud_id": mask_string("cloud-id-should-still-mask"),
    }


def test_user_response_reads_authentication_from_the_connection_state(
    connection: dict[str, object],
) -> None:
    connection["state"] = ConnectionState.NEEDS_RECONNECT
    integration = _integration(
        auth_method=IntegrationAuthMethod.OAUTH2,
        header_template={"Authorization": "Bearer {access_token}"},
    )

    response = _to_user_response(
        _external_app(app_type=ExternalAppType.SLACK), integration, _USER, _DB
    )

    assert response.authenticated is False
    assert response.credential_keys == []
    assert response.credential_values == {}


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
            ExternalAppType.ZENDESK,
            [r"https://acme\-support\.zendesk\.com/api/v2/.*"],
            ["https://acme-support.zendesk.com"],
        ),
        (
            ExternalAppType.LINEAR,
            ["https://api.linear.app/.*", r"https://api\.linear.app/.*"],
            [],
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
    connection: dict[str, object],  # noqa: ARG001
    app_type: ExternalAppType,
    patterns: list[str],
    origins: list[str],
) -> None:
    app = _external_app(app_type=app_type, upstream_url_patterns=patterns)

    response = _to_user_response(
        app, _integration(auth_method=None), _USER, _DB
    ).model_dump()

    assert response["service_urls"] == origins
    assert response["integration_id"] == 7
    assert set(response) == {
        "id",
        "integration_id",
        "name",
        "app_type",
        "credential_keys",
        "credential_values",
        "authenticated",
        "supports_oauth",
        "service_urls",
    }
    assert "secret" not in json.dumps(response["service_urls"])


def test_user_response_service_origins_default_to_empty() -> None:
    response = ExternalAppUserResponse(
        id=1,
        integration_id=1,
        name="Test App",
        app_type=ExternalAppType.CUSTOM,
        credential_keys=[],
        credential_values={},
        authenticated=True,
        supports_oauth=False,
    )

    assert response.service_urls == []
