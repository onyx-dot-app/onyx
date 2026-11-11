"""Unit tests for `validate_auth_template`."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType
from onyx.db.external_app import (
    create_external_app,
    resolve_masked_credentials,
    update_external_app,
    validate_auth_template,
)
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.encryption import mask_string
from onyx.utils.sensitive import SensitiveValue


def _sensitive_dict(value: dict[str, Any]) -> SensitiveValue[dict[str, Any]]:
    return SensitiveValue(
        encrypted_bytes=json.dumps(value).encode(),
        decrypt_fn=lambda value_bytes: value_bytes.decode(),
        is_json=True,
    )


def test_valid_template_passes() -> None:
    # No exception == valid.
    validate_auth_template(
        {"Authorization": "Bearer {api_key}"},
        {"api_key": "sk-123"},
    )


def test_empty_org_credentials_allowed() -> None:
    # A fully user-supplied credential app (org pre-fills nothing) is valid.
    validate_auth_template({"Authorization": "Bearer {api_key}"}, {})


def test_empty_template_and_credentials_allowed() -> None:
    # An allowlist-only app injects no headers and pre-fills nothing.
    validate_auth_template({}, {})


@pytest.mark.parametrize(
    "auth_template",
    [
        {"Authorization": ""},  # empty value
        {"Authorization": "   "},  # whitespace-only value
        {"": "Bearer x"},  # empty key
        {"   ": "Bearer x"},  # whitespace-only key
    ],
)
def test_malformed_template_rejected(auth_template: dict[str, Any]) -> None:
    with pytest.raises(OnyxError):
        validate_auth_template(auth_template, {})


def test_non_string_value_rejected() -> None:
    with pytest.raises(OnyxError):
        validate_auth_template({"Authorization": 123}, {})


def test_non_string_org_credential_key_rejected() -> None:
    with pytest.raises(OnyxError):
        validate_auth_template({"Authorization": "Bearer {api_key}"}, {"": "v"})


def test_resolve_masked_credentials_restores_existing_values() -> None:
    existing = _sensitive_dict(
        {
            "access_token": "USER_ACCESS_TOKEN",
            "workspace_id": "OLD_WORKSPACE_ID",
        }
    )

    resolved = resolve_masked_credentials(
        {
            "access_token": mask_string("USER_ACCESS_TOKEN"),
            "refresh_token": "NEW_REFRESH_TOKEN",
            "workspace_id": "NEW_WORKSPACE_ID",
        },
        existing,
    )

    assert resolved == {
        "access_token": "USER_ACCESS_TOKEN",
        "refresh_token": "NEW_REFRESH_TOKEN",
        "workspace_id": "NEW_WORKSPACE_ID",
    }


def test_resolve_masked_credentials_rejects_new_masked_values() -> None:
    with pytest.raises(OnyxError):
        resolve_masked_credentials(
            {"access_token": mask_string("USER_ACCESS_TOKEN")},
            None,
        )


@pytest.mark.parametrize("subdomain", ["acme", "https://ACME.zendesk.com/agent"])
def test_zendesk_create_resolves_gateway_from_account(subdomain: str) -> None:
    app = create_external_app(
        MagicMock(spec=Session),
        name="Zendesk",
        app_type=ExternalAppType.ZENDESK,
        upstream_url_patterns=["https://.*"],
        auth_template={"Authorization": "Bearer {access_token}"},
        organization_credentials={"subdomain": subdomain},
    )
    assert app.upstream_url_patterns == [r"https://acme\.zendesk\.com/api/v2/.*"]


def test_zendesk_update_restores_masks_before_resolving_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock(spec=Session)
    app = create_external_app(
        db,
        name="Zendesk",
        app_type=ExternalAppType.ZENDESK,
        upstream_url_patterns=[],
        auth_template={"Authorization": "Bearer {access_token}"},
        organization_credentials={"subdomain": "acme", "client_secret": "secret"},
    )
    monkeypatch.setattr("onyx.db.external_app.get_external_app_by_id", lambda *_: app)
    update_external_app(
        db,
        external_app_id=1,
        app_type=ExternalAppType.ZENDESK,
        upstream_url_patterns=[r"https://{subdomain}\.zendesk\.com/api/v2/.*"],
        organization_credentials={
            "subdomain": mask_string("acme"),
            "client_secret": mask_string("secret"),
        },
    )
    assert app.upstream_url_patterns == [r"https://acme\.zendesk\.com/api/v2/.*"]
    assert app.organization_credentials.get_value(apply_mask=False) == {
        "subdomain": "acme",
        "client_secret": "secret",
    }
    update_external_app(
        db,
        external_app_id=1,
        app_type=ExternalAppType.ZENDESK,
        organization_credentials={"subdomain": "https://other.zendesk.com/agent"},
    )
    assert app.upstream_url_patterns == [r"https://other\.zendesk\.com/api/v2/.*"]


@pytest.mark.parametrize("app_type", [ExternalAppType.SLACK, ExternalAppType.CUSTOM])
def test_fixed_host_and_custom_patterns_remain_admin_owned(
    app_type: ExternalAppType,
) -> None:
    patterns = [r"https://example.com/narrow-path"]
    app = create_external_app(
        MagicMock(spec=Session),
        name="App",
        app_type=app_type,
        upstream_url_patterns=patterns,
        auth_template={},
        organization_credentials={},
    )
    assert app.upstream_url_patterns == patterns


def test_zendesk_create_rejects_invalid_account_before_persistence() -> None:
    db = MagicMock(spec=Session)
    with pytest.raises(OnyxError):
        create_external_app(
            db,
            name="Zendesk",
            app_type=ExternalAppType.ZENDESK,
            upstream_url_patterns=["https://.*"],
            auth_template={},
            organization_credentials={"subdomain": "acme.example.com"},
        )
    db.add.assert_not_called()
