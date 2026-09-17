import os


# LTI 1.3 Platform Configuration
# These configure the Canvas (or other LMS) instance that Onyx integrates with.

# Issuer URL of the LTI platform (e.g. "https://canvas.instructure.com")
LTI_ISSUER: str | None = os.environ.get("LTI_ISSUER")

# Client ID assigned by the LMS (from Developer Keys in Canvas)
LTI_CLIENT_ID: str | None = os.environ.get("LTI_CLIENT_ID")

# OIDC authorization endpoint on the LMS
LTI_AUTH_LOGIN_URL: str | None = os.environ.get("LTI_AUTH_LOGIN_URL")

# Token endpoint on the LMS (for LTI Advantage service calls)
LTI_AUTH_TOKEN_URL: str | None = os.environ.get("LTI_AUTH_TOKEN_URL")

# JWKS endpoint on the LMS for verifying signed JWTs
LTI_JWKS_URL: str | None = os.environ.get("LTI_JWKS_URL")

# Canvas API/web base URL for connector setup. Optional because hosted Canvas
# often exposes the real school URL in launch claims.
LTI_CANVAS_BASE_URL: str | None = os.environ.get("LTI_CANVAS_BASE_URL")

# Deployment ID from the LMS
LTI_DEPLOYMENT_ID: str | None = os.environ.get("LTI_DEPLOYMENT_ID")

# Domains allowed to embed Onyx in an iframe (space-separated).
# Defaults to *.instructure.com for Canvas.
LTI_FRAME_ANCESTORS: str = os.environ.get(
    "LTI_FRAME_ANCESTORS", "https://*.instructure.com"
)

# TTL (seconds) for the OIDC nonce/state stored in Redis
LTI_NONCE_TTL_SECONDS: int = int(os.environ.get("LTI_NONCE_TTL_SECONDS", "300"))

# Canvas *API* developer key used for the per-instructor OAuth2 flow that
# replaces pasting a personal access token. This is a separate key from the
# LTI developer key (`LTI_CLIENT_ID`): Canvas forces scope enforcement on LTI
# keys and only allows LTI service scopes on them, so they cannot be used for
# the user authorization-code grant. A Canvas admin creates this key once per
# institution with the redirect URI + scopes reported by
# `GET /auth/lti/canvas-oauth/registration-info`.
LTI_CANVAS_OAUTH_CLIENT_ID: str | None = os.environ.get("LTI_CANVAS_OAUTH_CLIENT_ID")
LTI_CANVAS_OAUTH_CLIENT_SECRET: str | None = os.environ.get(
    "LTI_CANVAS_OAUTH_CLIENT_SECRET"
)

# TTL (seconds) for the Canvas OAuth `state` stored in Redis between opening
# the consent popup and Canvas redirecting back to the callback.
LTI_CANVAS_OAUTH_STATE_TTL_SECONDS: int = int(
    os.environ.get("LTI_CANVAS_OAUTH_STATE_TTL_SECONDS", "600")
)

# Whether to mirror Canvas course rosters into Onyx user groups. Defaults on
# whenever LTI is configured (see `lti_group_sync_enabled`).
_LTI_GROUP_SYNC_ENABLED_OVERRIDE: str | None = os.environ.get("LTI_GROUP_SYNC_ENABLED")

# How often (seconds) the periodic roster sync runs. Defaults to 15 minutes.
LTI_GROUP_SYNC_INTERVAL_SECONDS: int = int(
    os.environ.get("LTI_GROUP_SYNC_INTERVAL_SECONDS", "900")
)


def lti_is_configured() -> bool:
    """Return True if all required LTI env vars are set."""
    return all(
        [
            LTI_ISSUER,
            LTI_CLIENT_ID,
            LTI_AUTH_LOGIN_URL,
            LTI_JWKS_URL,
            LTI_DEPLOYMENT_ID,
        ]
    )


def lti_canvas_oauth_is_configured() -> bool:
    """Return True if instructors can connect Canvas via OAuth2.

    Requires the Canvas API developer key client id + secret on top of the
    base LTI config. When False the instructor setup UI falls back to the
    legacy paste-a-personal-access-token flow.
    """
    return lti_is_configured() and bool(
        LTI_CANVAS_OAUTH_CLIENT_ID and LTI_CANVAS_OAUTH_CLIENT_SECRET
    )


def lti_group_sync_enabled() -> bool:
    """Return True if Canvas roster → Onyx user group sync should run.

    Requires the LTI token endpoint (for minting NRPS service tokens) on top of
    the base LTI config. Defaults on when configured; set LTI_GROUP_SYNC_ENABLED
    to "false"/"0" to disable.
    """
    if _LTI_GROUP_SYNC_ENABLED_OVERRIDE is not None:
        if _LTI_GROUP_SYNC_ENABLED_OVERRIDE.strip().lower() in ("false", "0", "no"):
            return False
    return lti_is_configured() and bool(LTI_AUTH_TOKEN_URL)
