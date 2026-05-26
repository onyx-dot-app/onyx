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
