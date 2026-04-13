import os

from shared_configs.configs import SENTRY_DSN


def resolve_sentry_dsn() -> str | None:
    """Resolve the Sentry DSN.

    Priority:
    1. Explicit SENTRY_DSN env var (any deployment — cloud sets this in infra)
    2. Bundled DSN (ONYX_BUNDLED_SENTRY_DSN + ENABLE_ONYX_SENTRY_REPORTING=true)
    3. None (disabled)

    The bundled DSN is injected at build time via the ONYX_BUNDLED_SENTRY_DSN
    env var (never hardcoded in source). For managed customer clusters, Onyx
    sets both env vars. Self-hosted customers can opt in by setting both.
    """
    if SENTRY_DSN:
        return SENTRY_DSN

    bundled_dsn = os.environ.get("ONYX_BUNDLED_SENTRY_DSN")
    opt_in = os.environ.get("ENABLE_ONYX_SENTRY_REPORTING", "").lower() == "true"
    if bundled_dsn and opt_in:
        return bundled_dsn

    return None
