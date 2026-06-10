from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator
from typing_extensions import Self

PASSWORD_LENGTH_CAP = 256
# 4 = one char per required character class; lower would lock out signups
# once all four require_* flags are on.
PASSWORD_MAX_LENGTH_FLOOR = 4


_OPERATOR_LOCKED_MARKER = "operator_locked"


def _operator_locked() -> dict[str, bool]:
    """Field marker: operator (env) only — tenant admins can't override."""
    return {_OPERATOR_LOCKED_MARKER: True}


def _tenant_editable() -> dict[str, bool]:
    """Field marker: tenant admins may override at runtime."""
    return {_OPERATOR_LOCKED_MARKER: False}


class SecuritySettingsOverrides(BaseModel):
    """Wire/storage shape. Absent / None on any field means "use env default"."""

    # hide_input_in_errors strips offending input_value from ValidationError
    # messages — they surface back through the PUT envelope and would otherwise
    # leak any sensitive value an admin sends (any future secret-shaped field).
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
        # Mirror env-parse for VALID_EMAIL_DOMAINS exactly. NO dedup — env
        # parser doesn't dedupe and behavior must match byte-for-byte.
        return [d.strip().lower() for d in v if d.strip()]


def _derive_operator_locked_fields() -> frozenset[str]:
    """Names of fields whose ``operator_locked`` marker is True.

    Raises at module import if any field is missing the marker — forces an
    explicit yes/no at declaration rather than a silent tenant-editable default.
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
