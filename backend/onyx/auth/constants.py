"""Authentication constants shared across auth modules."""

from datetime import timedelta

from onyx.db.enums import Permission

# API Key constants
API_KEY_PREFIX = "on_"
DEPRECATED_API_KEY_PREFIX = "dn_"
API_KEY_LENGTH = 192

# PAT constants
PAT_PREFIX = "onyx_pat_"
PAT_LENGTH = 192

# OAuth provider constants
OAUTH_PROVIDER_ACCESS_TOKEN_PREFIX = "onyx_oat_"
OAUTH_PROVIDER_REFRESH_TOKEN_PREFIX = "onyx_ort_"
OAUTH_PROVIDER_CODE_PREFIX = "onyx_oac_"
# The only scope an OAuth provider grant carries.
OAUTH_PROVIDER_SCOPE = Permission.READ_SEARCH.value
# `secrets.token_urlsafe(32)` output: token secrets, request handles and CSRF
# tokens. An S256 PKCE challenge has the same shape.
OAUTH_PROVIDER_SECRET_PATTERN = r"[A-Za-z0-9_-]{43}"
OAUTH_PROVIDER_TENANT_PATTERN = r"[A-Za-z0-9_-]{1,63}"
OAUTH_PROVIDER_MAX_URL_LENGTH = 2048
AUTHORIZATION_REQUEST_TTL_SECONDS = 10 * 60
AUTHORIZATION_CODE_TTL_SECONDS = 60
OAUTH_PROVIDER_ACCESS_LIFETIME = timedelta(minutes=15)
OAUTH_PROVIDER_GRANT_LIFETIME = timedelta(days=30)
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}

# SCIM constants. Defined here rather than in `ee` so that tenant extraction in
# `onyx.auth.utils` can recognise a SCIM token without importing from `ee`.
SCIM_TOKEN_PREFIX = "onyx_scim_"
SCIM_TOKEN_LENGTH = 48

# Shared header constants
API_KEY_HEADER_NAME = "Authorization"
API_KEY_HEADER_ALTERNATIVE_NAME = "X-Onyx-Authorization"
BEARER_PREFIX = "Bearer "
