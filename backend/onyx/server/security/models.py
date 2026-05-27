from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import field_validator


class SecuritySettingsOverrides(BaseModel):
    """Wire/storage shape for runtime security overrides.

    Every field is optional. Absent / None means "use the env-derived default."
    Stored in KV with model_dump(exclude_none=True) so absent fields stay
    absent. extra="forbid" rejects unknown keys.
    """

    model_config = ConfigDict(extra="forbid")

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
        # Match backend/onyx/configs/app_configs.py:174-185 env-parse behavior
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
