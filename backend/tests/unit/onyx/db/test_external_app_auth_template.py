"""Unit tests for `validate_auth_template`, `decrypt_credentials_or_empty`,
`is_user_authenticated_for_app`, and `resolve_masked_credentials`."""

from __future__ import annotations

import json
from typing import Any

import pytest

from onyx.configs.constants import MASK_CREDENTIAL_CHAR
from onyx.db.external_app import decrypt_credentials_or_empty
from onyx.db.external_app import is_user_authenticated_for_app
from onyx.db.external_app import resolve_masked_credentials
from onyx.db.external_app import validate_auth_template
from onyx.db.models import ExternalApp
from onyx.db.models import ExternalAppUserCredential
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.sensitive import SensitiveValue

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bad_sensitive() -> SensitiveValue[dict[str, Any]]:
    """SensitiveValue whose decryption raises UnicodeDecodeError (a ValueError subclass)."""
    return SensitiveValue(
        encrypted_bytes=b"\xa5garbage",
        decrypt_fn=lambda b: b.decode(),  # raises UnicodeDecodeError on \xa5
        is_json=True,
    )


def _good_sensitive(data: dict[str, Any]) -> SensitiveValue[dict[str, Any]]:
    """SensitiveValue that decrypts successfully to ``data``."""
    raw = json.dumps(data).encode()
    return SensitiveValue(
        encrypted_bytes=raw,
        decrypt_fn=lambda b: b.decode(),
        is_json=True,
    )


def _make_app(
    org_creds: SensitiveValue[dict[str, Any]],
    auth_template: dict[str, Any],
    app_id: int = 1,
) -> ExternalApp:
    """Transient ExternalApp with the given credentials and auth_template."""
    app = ExternalApp(
        organization_credentials=org_creds,
        auth_template=auth_template,
    )
    # Set id directly — not a DB-generated column in this context.
    app.__dict__["id"] = app_id
    return app


def _make_user_cred(
    user_credentials: SensitiveValue[dict[str, Any]],
) -> ExternalAppUserCredential:
    """Transient ExternalAppUserCredential with the given credentials."""
    return ExternalAppUserCredential(user_credentials=user_credentials)


# ---------------------------------------------------------------------------
# decrypt_credentials_or_empty
# ---------------------------------------------------------------------------


def test_decrypt_credentials_or_empty_returns_empty_for_bad_bytes() -> None:
    result = decrypt_credentials_or_empty(
        _bad_sensitive(), apply_mask=False, context="test"
    )
    assert result == {}


def test_decrypt_credentials_or_empty_returns_dict_for_valid() -> None:
    data = {"token": "secret"}
    result = decrypt_credentials_or_empty(
        _good_sensitive(data), apply_mask=False, context="test"
    )
    assert result == data


# ---------------------------------------------------------------------------
# is_user_authenticated_for_app
# ---------------------------------------------------------------------------


def test_is_user_authenticated_undecryptable_org_creds_no_user_cred() -> None:
    """Undecryptable org creds count as no pre-fill: all placeholders required,
    no user_cred → False, and no raise."""
    app = _make_app(
        org_creds=_bad_sensitive(),
        auth_template={"Authorization": "Bearer {token}"},
    )
    result = is_user_authenticated_for_app(app, user_cred=None)
    assert result is False


def test_is_user_authenticated_undecryptable_org_creds_valid_user_cred() -> None:
    """Undecryptable org creds, user_cred with the required key → True."""
    app = _make_app(
        org_creds=_bad_sensitive(),
        auth_template={"Authorization": "Bearer {token}"},
    )
    user_cred = _make_user_cred(_good_sensitive({"token": "my-token"}))
    result = is_user_authenticated_for_app(app, user_cred=user_cred)
    assert result is True


# ---------------------------------------------------------------------------
# resolve_masked_credentials
# ---------------------------------------------------------------------------


def _masked_value() -> str:
    """A value that passes is_masked_credential()."""
    return MASK_CREDENTIAL_CHAR * 12


def test_resolve_masked_credentials_undecryptable_existing_masked_raises() -> None:
    """Masked incoming + undecryptable existing → OnyxError (can't restore)."""
    with pytest.raises(OnyxError):
        resolve_masked_credentials(
            {"api_key": _masked_value()},
            existing=_bad_sensitive(),
        )


def test_resolve_masked_credentials_undecryptable_existing_plain_value() -> None:
    """Unmasked incoming value + undecryptable existing → incoming value returned as-is."""
    result = resolve_masked_credentials(
        {"api_key": "new-plain-value"},
        existing=_bad_sensitive(),
    )
    assert result == {"api_key": "new-plain-value"}


# ---------------------------------------------------------------------------
# validate_auth_template (existing tests follow)
# ---------------------------------------------------------------------------


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
