"""Single source of truth for PostgreSQL TLS configuration.

Two drivers, two mechanisms:

- psycopg2 (sync) speaks libpq directly, so it takes ``sslmode`` / ``sslrootcert``
  as ``connect_args`` keys.
- asyncpg (async) does NOT accept libpq ``sslmode`` keys. Verifying against a
  custom CA requires an ``ssl.SSLContext`` passed as ``connect_args["ssl"]``;
  passing the bare mode string would only use the system CA store and ignore our
  bundle.

Mutual TLS (``POSTGRES_SSLCERT`` / ``POSTGRES_SSLKEY``) presents a client
certificate via libpq keys for psycopg2 and ``SSLContext.load_cert_chain`` for
asyncpg.

IAM auth (when enabled) always takes precedence — it enforces its own TLS — so
the explicit ``POSTGRES_SSL*`` settings only apply when IAM is off.
"""

import functools
import ssl

from onyx.configs.app_configs import POSTGRES_SSLCERT
from onyx.configs.app_configs import POSTGRES_SSLKEY
from onyx.configs.app_configs import POSTGRES_SSLKEY_PASSWORD
from onyx.configs.app_configs import POSTGRES_SSLMODE
from onyx.configs.app_configs import POSTGRES_SSLROOTCERT
from onyx.configs.app_configs import USE_IAM_AUTH
from onyx.db.engine.iam_auth import create_ssl_context_if_iam
from onyx.utils.tls import build_ssl_context

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
    # Client certificate for mutual TLS — libpq consumes these natively.
    if POSTGRES_SSLCERT:
        args["sslcert"] = POSTGRES_SSLCERT
    if POSTGRES_SSLKEY:
        args["sslkey"] = POSTGRES_SSLKEY
    if POSTGRES_SSLKEY_PASSWORD:
        args["sslpassword"] = POSTGRES_SSLKEY_PASSWORD
    return args


@functools.cache
def create_pg_ssl_context() -> ssl.SSLContext | str | None:
    """SSL config for the asyncpg engine (and async Alembic), assigned to
    ``connect_args["ssl"]``.

    Returns:
      - an ``ssl.SSLContext`` for IAM auth and for ``require`` / ``verify-ca`` /
        ``verify-full`` (the latter two verifying against ``POSTGRES_SSLROOTCERT``;
        all three present ``POSTGRES_SSLCERT`` / ``POSTGRES_SSLKEY`` for mutual TLS
        when configured)
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

    if POSTGRES_SSLMODE == "require":
        # Encrypt without verifying the server identity. The system CA bundle is
        # still loaded by create_default_context but is never consulted because
        # verify_mode is CERT_NONE; we pass no custom CA.
        verify_mode, check_hostname, ca_certs = ssl.CERT_NONE, False, None
    else:
        # verify-ca / verify-full — verify the server cert against the CA bundle.
        # POSTGRES_SSLROOTCERT is guaranteed set for these modes by the config
        # validation in app_configs.
        verify_mode = ssl.CERT_REQUIRED
        check_hostname = POSTGRES_SSLMODE == "verify-full"
        ca_certs = POSTGRES_SSLROOTCERT

    return build_ssl_context(
        verify_mode=verify_mode,
        check_hostname=check_hostname,
        ca_certs=ca_certs,
        certfile=POSTGRES_SSLCERT,
        keyfile=POSTGRES_SSLKEY,
        key_password=POSTGRES_SSLKEY_PASSWORD,
    )
