"""Single source of truth for PostgreSQL TLS configuration.

Two drivers, two mechanisms:

- psycopg2 (sync) speaks libpq directly, so it takes ``sslmode`` / ``sslrootcert``
  as ``connect_args`` keys.
- asyncpg (async) does NOT accept libpq ``sslmode`` keys. Verifying against a
  custom CA requires an ``ssl.SSLContext`` passed as ``connect_args["ssl"]``;
  passing the bare mode string would only use the system CA store and ignore our
  bundle.

IAM auth (when enabled) always takes precedence — it enforces its own TLS — so
the explicit ``POSTGRES_SSLMODE`` / ``POSTGRES_SSLROOTCERT`` settings only apply
when IAM is off.
"""

import functools
import ssl

from onyx.configs.app_configs import POSTGRES_SSLMODE
from onyx.configs.app_configs import POSTGRES_SSLROOTCERT
from onyx.configs.app_configs import USE_IAM_AUTH
from onyx.db.engine.iam_auth import create_ssl_context_if_iam

# Modes that require an encrypted connection and therefore an explicit
# SSLContext on the asyncpg side.
_ENFORCED_SSL_MODES = frozenset({"require", "verify-ca", "verify-full"})


def pg_ssl_psycopg2_connect_args() -> dict[str, str]:
    """libpq SSL params for the sync psycopg2 engine.

    Empty when IAM auth is enabled (the IAM ``do_connect`` listener sets
    ``sslmode`` / ``sslrootcert`` itself) or when no explicit SSL is configured.
    """
    if USE_IAM_AUTH or not POSTGRES_SSLMODE:
        return {}
    args = {"sslmode": POSTGRES_SSLMODE}
    if POSTGRES_SSLROOTCERT:
        args["sslrootcert"] = POSTGRES_SSLROOTCERT
    return args


@functools.cache
def create_pg_ssl_context() -> ssl.SSLContext | str | None:
    """SSL config for the asyncpg engine (and async Alembic), assigned to
    ``connect_args["ssl"]``.

    Returns:
      - an ``ssl.SSLContext`` for IAM auth and for ``require`` / ``verify-ca`` /
        ``verify-full`` (the latter two verifying against ``POSTGRES_SSLROOTCERT``)
      - the raw mode string for ``allow`` / ``prefer`` so asyncpg performs its
        native opportunistic-TLS-with-plaintext-fallback
      - ``None`` for ``disable`` / unset (no SSL)
    """
    if USE_IAM_AUTH:
        return create_ssl_context_if_iam()

    if not POSTGRES_SSLMODE or POSTGRES_SSLMODE == "disable":
        return None

    if POSTGRES_SSLMODE not in _ENFORCED_SSL_MODES:
        # allow / prefer — let asyncpg decide, with plaintext fallback.
        return POSTGRES_SSLMODE

    context = ssl.create_default_context(cafile=POSTGRES_SSLROOTCERT or None)
    if POSTGRES_SSLMODE == "verify-full":
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
    elif POSTGRES_SSLMODE == "verify-ca":
        context.check_hostname = False
        context.verify_mode = ssl.CERT_REQUIRED
    else:  # require — encrypt without verifying the server identity.
        # check_hostname must be cleared before relaxing verify_mode.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context
