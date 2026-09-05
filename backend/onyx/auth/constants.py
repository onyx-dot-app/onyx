"""Authentication constants shared across auth modules."""

# API Key constants
API_KEY_PREFIX = "on_"
DEPRECATED_API_KEY_PREFIX = "dn_"
API_KEY_LENGTH = 192

# PAT constants
PAT_PREFIX = "onyx_pat_"
PAT_LENGTH = 192

# SCIM constants. Defined here rather than in `ee` so that tenant extraction in
# `onyx.auth.utils` can recognise a SCIM token without importing from `ee`.
SCIM_TOKEN_PREFIX = "onyx_scim_"
SCIM_TOKEN_LENGTH = 48

# Shared header constants
API_KEY_HEADER_NAME = "Authorization"
API_KEY_HEADER_ALTERNATIVE_NAME = "X-Onyx-Authorization"
BEARER_PREFIX = "Bearer "
