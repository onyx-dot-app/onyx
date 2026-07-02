"""Model-level tests (validators, field metadata) — no external deps."""

from typing import Any

import pytest
from pydantic import ValidationError

from onyx.server.security.models import _derive_operator_locked_fields
from onyx.server.security.models import _operator_locked
from onyx.server.security.models import _tenant_editable
from onyx.server.security.models import OPERATOR_LOCKED_FIELDS
from onyx.server.security.models import PASSWORD_LENGTH_CAP
from onyx.server.security.models import PASSWORD_MAX_LENGTH_FLOOR
from onyx.server.security.models import SecuritySettings
from onyx.server.security.models import SecuritySettingsOverrides
from onyx.server.security.models import SSRFProtectionLevel

_VALID_EFFECTIVE_KWARGS: dict[str, Any] = {
    "user_directory_admin_only": False,
    "track_external_idp_expiry": False,
    "ssrf_protection_level": SSRFProtectionLevel.VALIDATE_LLM,
    "mask_credential_prefix": True,
    "valid_email_domains": (),
    "password_min_length": 8,
    "password_max_length": 64,
    "password_require_uppercase": True,
    "password_require_lowercase": True,
    "password_require_digit": True,
    "password_require_special_char": False,
}


def test_every_overrides_field_declares_operator_locked_marker() -> None:
    """Pins the contract enforced at module import — every field must carry
    the marker, with a bool value."""
    for name, info in SecuritySettingsOverrides.model_fields.items():
        extras = info.json_schema_extra
        assert isinstance(extras, dict), f"{name}: json_schema_extra must be a dict"
        assert "operator_locked" in extras, (
            f"{name}: missing operator_locked marker — use "
            f"Field(..., json_schema_extra=_operator_locked()) or _tenant_editable()"
        )
        assert isinstance(extras["operator_locked"], bool), (
            f"{name}: operator_locked must be a bool"
        )


def test_operator_locked_fields_matches_marker_declarations() -> None:
    expected = {
        name
        for name, info in SecuritySettingsOverrides.model_fields.items()
        if isinstance(info.json_schema_extra, dict)
        and info.json_schema_extra.get("operator_locked") is True
    }
    assert OPERATOR_LOCKED_FIELDS == frozenset(expected)


def test_derivation_works_on_a_fresh_call() -> None:
    assert _derive_operator_locked_fields() == OPERATOR_LOCKED_FIELDS


def test_helper_marker_factories_produce_independent_dicts() -> None:
    """Each factory call returns a fresh dict so Pydantic field metadata is
    never shared by reference."""
    a = _operator_locked()
    b = _operator_locked()
    assert a is not b
    a.clear()
    assert b["operator_locked"] is True
    assert _tenant_editable()["operator_locked"] is False


def _effective_with(**overrides: Any) -> dict[str, Any]:
    return {**_VALID_EFFECTIVE_KWARGS, **overrides}


def test_security_settings_accepts_valid_default_state() -> None:
    SecuritySettings.model_validate(_VALID_EFFECTIVE_KWARGS)


def test_security_settings_rejects_negative_min_length() -> None:
    with pytest.raises(ValidationError):
        SecuritySettings.model_validate(_effective_with(password_min_length=-1))


def test_security_settings_rejects_max_length_below_floor() -> None:
    with pytest.raises(ValidationError):
        SecuritySettings.model_validate(
            _effective_with(
                password_min_length=0,
                password_max_length=PASSWORD_MAX_LENGTH_FLOOR - 1,
            )
        )


def test_security_settings_rejects_max_length_above_cap() -> None:
    with pytest.raises(ValidationError):
        SecuritySettings.model_validate(
            _effective_with(password_max_length=PASSWORD_LENGTH_CAP + 1)
        )


def test_security_settings_rejects_min_greater_than_max() -> None:
    with pytest.raises(ValidationError):
        SecuritySettings.model_validate(
            _effective_with(password_min_length=20, password_max_length=10)
        )


def test_overrides_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        SecuritySettingsOverrides.model_validate({"not_a_real_field": True})


def test_overrides_valid_email_domains_normalized() -> None:
    """Strip, lowercase, drop empties; preserve order; no dedup."""
    parsed = SecuritySettingsOverrides.model_validate(
        {"valid_email_domains": [" ACME.com", "", "  ", "Foo.IO", "acme.com"]}
    )
    assert parsed.valid_email_domains == ["acme.com", "foo.io", "acme.com"]


def test_overrides_hide_input_in_errors() -> None:
    """ValidationError must not echo the offending input — that's how an
    admin's secret-shaped value would leak out of the PUT response envelope.
    """
    sentinel = "DO-NOT-LEAK-12345"
    try:
        SecuritySettingsOverrides.model_validate({"password_min_length": sentinel})
    except ValidationError as e:
        assert sentinel not in str(e)
    else:  # pragma: no cover
        raise AssertionError("expected ValidationError")
