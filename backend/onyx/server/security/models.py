from pydantic import BaseModel
from pydantic import Field


class SecuritySettings(BaseModel):
    """Tenant-scoped security hardening settings.

    Every field is Optional — when unset, the corresponding env-var constant
    is used as the fallback at the call site. This preserves existing
    deployment behavior until an admin explicitly saves a value.
    """

    # Account & access — always editable
    user_directory_admin_only: bool | None = None
    track_external_idp_expiry: bool | None = None

    # Operator-locked in multi-tenant mode (server enforces; UI hides)
    require_email_verification: bool | None = None
    mask_credential_prefix: bool | None = None
    valid_email_domains: list[str] | None = None

    # Password policy — operator-locked in multi-tenant
    password_min_length: int | None = Field(default=None, ge=1, le=1024)
    password_max_length: int | None = Field(default=None, ge=1, le=1024)
    password_require_uppercase: bool | None = None
    password_require_lowercase: bool | None = None
    password_require_digit: bool | None = None
    password_require_special_char: bool | None = None


class SecurityStatus(BaseModel):
    """Read-only audit panel: reports whether env-only security knobs are
    configured. Returns booleans/labels only, never secret values.
    """

    auth_type: str
    multi_tenant: bool
    encryption_key_configured: bool
    user_auth_secret_configured: bool
    oauth_configured: bool
    oidc_configured: bool
    oidc_pkce_enabled: bool
    saml_configured: bool
    jwt_public_key_configured: bool
    cors_restricted: bool
