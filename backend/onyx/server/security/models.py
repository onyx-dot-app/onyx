from pydantic import BaseModel
from pydantic import ConfigDict
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


class SecuritySettingsOverrides(BaseModel):
    """Wire/storage shape for runtime security overrides.

    Every field is optional. Absent / None means "use the env-derived default."
    Stored in KV with model_dump(exclude_none=True) so absent fields stay
    absent. extra="forbid" rejects unknown keys.
    """

    # hide_input_in_errors: ValidationError.__str__ is surfaced to callers via
    # the PUT handler's INVALID_INPUT envelope. The default Pydantic message
    # includes the offending input_value, which would echo back any sensitive
    # value an admin sends (today: low-risk bools/ints; future: any added
    # secret-shaped field). Strip input from error messages so we never leak.
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    user_directory_admin_only: bool | None = None
    track_external_idp_expiry: bool | None = None
    mask_credential_prefix: bool | None = None
    valid_email_domains: list[str] | None = None
    password_min_length: int | None = None
    password_max_length: int | None = None
    password_require_uppercase: bool | None = None
    password_require_lowercase: bool | None = None
    password_require_digit: bool | None = None
    password_require_special_char: bool | None = None

    @field_validator("valid_email_domains")
    @classmethod
    def _normalize_domains(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        # Mirror the env-parse behavior for VALID_EMAIL_DOMAINS in app_configs
        # exactly: strip, lowercase, drop empties. NO dedup (env parser does
        # not dedupe). Order preserved.
        return [d.strip().lower() for d in v if d.strip()]


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
            raise ValueError(
                f"password_max_length must be <= {PASSWORD_LENGTH_CAP}"
            )
        if self.password_min_length > self.password_max_length:
            raise ValueError("password_min_length must be <= password_max_length")
        return self
