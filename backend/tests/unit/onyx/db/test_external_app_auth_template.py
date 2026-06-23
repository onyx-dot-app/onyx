"""Unit tests for `validate_auth_template`."""

from __future__ import annotations

import json
from typing import Any

import pytest

from onyx.db.external_app import mask_external_app_user_credentials
from onyx.db.external_app import resolve_masked_credentials
from onyx.db.external_app import validate_auth_template
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.encryption import mask_credential_dict
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
            "expires_at": 1_234,
        }
    )

    resolved = resolve_masked_credentials(
        {
            "access_token": mask_string("USER_ACCESS_TOKEN"),
            "refresh_token": "NEW_REFRESH_TOKEN",
            "expires_at": 5_678,
        },
        existing,
    )

    assert resolved == {
        "access_token": "USER_ACCESS_TOKEN",
        "refresh_token": "NEW_REFRESH_TOKEN",
        "expires_at": 5_678,
    }


def test_resolve_masked_credentials_rejects_new_masked_values() -> None:
    with pytest.raises(OnyxError):
        resolve_masked_credentials(
            {"access_token": mask_string("USER_ACCESS_TOKEN")},
            None,
        )


def test_external_app_user_credential_masker_has_no_connector_allowlist() -> None:
    cloud_id = "cloud-id-should-mask"
    cloud_name = "nested-cloud-name-should-mask"
    credentials = {
        "cloud_id": cloud_id,
        "nested": {"cloud_name": cloud_name},
    }

    assert mask_credential_dict(credentials)["cloud_id"] == credentials["cloud_id"]
    assert mask_external_app_user_credentials(credentials) == {
        "cloud_id": mask_string(cloud_id),
        "nested": {
            "cloud_name": mask_string(cloud_name),
        },
    }
