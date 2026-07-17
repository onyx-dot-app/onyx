"""Shared helper for constructing ``ssl.SSLContext`` objects from the common
TLS primitives (CA bundle, verify mode, optional client cert/key for mTLS).

Each service maps its own env-var vocabulary (libpq ``sslmode`` for Postgres,
``cert_reqs`` for Redis, etc.) down to these arguments so the context-building
and client-certificate logic isn't duplicated per service.
"""

import ssl


def build_ssl_context(
    *,
    verify_mode: ssl.VerifyMode,
    check_hostname: bool,
    ca_certs: str | None = None,
    certfile: str | None = None,
    keyfile: str | None = None,
    key_password: str | None = None,
) -> ssl.SSLContext:
    """Build an ``ssl.SSLContext``.

    ``ca_certs`` is the CA bundle to verify the server against (``None`` uses the
    system trust store). ``certfile`` / ``keyfile`` enable mutual TLS by
    presenting a client certificate. ``verify_mode`` / ``check_hostname`` control
    how the server certificate is validated.
    """
    context = ssl.create_default_context(cafile=ca_certs)
    # check_hostname must be cleared before relaxing verify_mode to CERT_NONE,
    # otherwise SSLContext raises.
    context.check_hostname = check_hostname
    context.verify_mode = verify_mode
    if certfile:
        context.load_cert_chain(
            certfile=certfile, keyfile=keyfile, password=key_password
        )
    return context
