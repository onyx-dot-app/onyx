from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator
from typing_extensions import Self

# Sanity cap for password length: env default is 64 today, so a 256 ceiling
# does not change any current behavior.
PASSWORD_LENGTH_CAP = 256
# Floor for ``password_max_length``: one char per required character class
# (4 classes total). Anything lower would silently lock out every signup
# once all four require_* flags are on.
PASSWORD_MAX_LENGTH_FLOOR = 4


# Marker key under each field's ``json_schema_extra`` declaring whether tenant
# admins may override that field in multi-tenant deployments. Adding a new
# field without this marker is a hard error at module import — see the
# derivation block below the model.
_OPERATOR_LOCKED_MARKER = "operator_locked"


def _operator_locked() -> dict[str, bool]:
    """Marker for fields that, in multi-tenant deployments, are controlled by
    the operator (env) only — tenant admins cannot override at runtime."""
    return {_OPERATOR_LOCKED_MARKER: True}


def _tenant_editable() -> dict[str, bool]:
    """Marker for fields that tenant admins may override at runtime in any
    deployment."""
    return {_OPERATOR_LOCKED_MARKER: False}


class SecuritySettingsOverrides(BaseModel):
    """Wire/storage shape for runtime security overrides.

    Every field is optional. Absent / None means "use the env-derived default."
    Persisted to the ``security_settings`` table with one column per field;
    ``None`` writes NULL and the loader treats NULL as "fall back to env".
    ``extra="forbid"`` rejects unknown keys.

    Each field carries an ``operator_locked`` marker via ``json_schema_extra``.
    Adding a new field without picking a side raises at module import (see
    derivation of ``OPERATOR_LOCKED_FIELDS`` below).
    """

    # hide_input_in_errors: ValidationError.__str__ is surfaced to callers via
    # the PUT handler's INVALID_INPUT envelope. The default Pydantic message
    # includes the offending input_value, which would echo back any sensitive
    # value an admin sends (today: low-risk bools/ints; future: any added
    # secret-shaped field). Strip input from error messages so we never leak.
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    user_directory_admin_only: bool | None = Field(
        default=None, json_schema_extra=_tenant_editable()
    )
    track_external_idp_expiry: bool | None = Field(
        default=None, json_schema_extra=_tenant_editable()
    )
    mask_credential_prefix: bool | None = Field(
        default=None, json_schema_extra=_operator_locked()
    )
    valid_email_domains: list[str] | None = Field(
        default=None, json_schema_extra=_operator_locked()
    )
    password_min_length: int | None = Field(
        default=None, json_schema_extra=_operator_locked()
    )
    password_max_length: int | None = Field(
        default=None, json_schema_extra=_operator_locked()
    )
    password_require_uppercase: bool | None = Field(
        default=None, json_schema_extra=_operator_locked()
    )
    password_require_lowercase: bool | None = Field(
        default=None, json_schema_extra=_operator_locked()
    )
    password_require_digit: bool | None = Field(
        default=None, json_schema_extra=_operator_locked()
    )
    password_require_special_char: bool | None = Field(
        default=None, json_schema_extra=_operator_locked()
    )

    @field_validator("valid_email_domains")
    @classmethod
    def _normalize_domains(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        # Mirror the env-parse behavior for VALID_EMAIL_DOMAINS in app_configs
        # exactly: strip, lowercase, drop empties. NO dedup (env parser does
        # not dedupe). Order preserved.
        return [d.strip().lower() for d in v if d.strip()]


def _derive_operator_locked_fields() -> frozenset[str]:
    """Read each field's ``operator_locked`` marker and return the set of
    locked field names. Raises at import time if any field is missing the
    marker — so adding a new field forces an explicit yes/no decision rather
    than a silent omission that defaults to tenant-editable.
    """
    locked: set[str] = set()
    missing: list[str] = []
    for name, info in SecuritySettingsOverrides.model_fields.items():
        extras = info.json_schema_extra
        if not isinstance(extras, dict) or _OPERATOR_LOCKED_MARKER not in extras:
            missing.append(name)
            continue
        if extras[_OPERATOR_LOCKED_MARKER]:
            locked.add(name)
    if missing:
        raise RuntimeError(
            "SecuritySettingsOverrides fields missing operator_locked marker: "
            f"{sorted(missing)}. Use Field(..., json_schema_extra=_operator_locked()) "
            f"or _tenant_editable() to declare each field's status."
        )
    return frozenset(locked)


OPERATOR_LOCKED_FIELDS: frozenset[str] = _derive_operator_locked_fields()


class SecuritySettings(BaseModel):
    """Effective, env-merged, immutable security settings."""

    model_config = ConfigDict(frozen=True)

    user_directory_admin_only: bool
    track_external_idp_expiry: bool
    mask_credential_prefix: bool
    valid_email_domains: tuple[str, ...]
    password_min_length: int
    password_max_length: int
    password_require_uppercase: bool
    password_require_lowercase: bool
    password_require_digit: bool
    password_require_special_char: bool

    @model_validator(mode="after")
    def _check_password_length_invariants(self) -> Self:
        if self.password_min_length < 0:
            raise ValueError("password_min_length must be >= 0")
        if self.password_max_length < PASSWORD_MAX_LENGTH_FLOOR:
            raise ValueError(
                f"password_max_length must be >= {PASSWORD_MAX_LENGTH_FLOOR}"
            )
        if self.password_max_length > PASSWORD_LENGTH_CAP:
            raise ValueError(f"password_max_length must be <= {PASSWORD_LENGTH_CAP}")
        if self.password_min_length > self.password_max_length:
            raise ValueError("password_min_length must be <= password_max_length")
        return self
