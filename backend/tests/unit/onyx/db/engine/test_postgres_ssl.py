import importlib
import os
import ssl
from types import ModuleType
from unittest.mock import patch

import certifi
import pytest

# A real, parseable CA bundle so `verify-ca` / `verify-full` can actually load
# certs (the resolution logic refuses to fabricate a context without one).
_CA_BUNDLE = certifi.where()


def _reload_pg_ssl() -> ModuleType:
    """Reload app_configs then pg_ssl so both pick up freshly-parsed env vars
    (each binds the POSTGRES_SSL* constants at import time)."""
    import onyx.configs.app_configs as app_configs

    importlib.reload(app_configs)
    import onyx.db.engine.pg_ssl as module

    return importlib.reload(module)


def _clear_ssl_env() -> None:
    for var in ("POSTGRES_SSLMODE", "POSTGRES_SSLROOTCERT", "USE_IAM_AUTH"):
        os.environ.pop(var, None)


@pytest.fixture(autouse=True)
def _restore_modules_after_test() -> object:
    """These tests reload app_configs / pg_ssl with custom env bound at import
    time. Restore both to their default (clean-env) state afterwards so the
    module-level constants don't leak into other test files in the session."""
    yield
    _clear_ssl_env()
    _reload_pg_ssl()


# --- psycopg2 (sync) connect_args ----------------------------------------


def test_psycopg2_args_empty_when_unset() -> None:
    with patch.dict(os.environ, {}, clear=False):
        _clear_ssl_env()
        module = _reload_pg_ssl()
        assert module.pg_ssl_psycopg2_connect_args() == {}


def test_psycopg2_args_require_has_no_rootcert() -> None:
    with patch.dict(os.environ, {}, clear=False):
        _clear_ssl_env()
        os.environ["POSTGRES_SSLMODE"] = "require"
        module = _reload_pg_ssl()
        assert module.pg_ssl_psycopg2_connect_args() == {"sslmode": "require"}


def test_psycopg2_args_verify_full_includes_rootcert() -> None:
    with patch.dict(os.environ, {}, clear=False):
        _clear_ssl_env()
        os.environ["POSTGRES_SSLMODE"] = "verify-full"
        os.environ["POSTGRES_SSLROOTCERT"] = _CA_BUNDLE
        module = _reload_pg_ssl()
        assert module.pg_ssl_psycopg2_connect_args() == {
            "sslmode": "verify-full",
            "sslrootcert": _CA_BUNDLE,
        }


def test_psycopg2_args_empty_when_iam_takes_precedence() -> None:
    """IAM enforces its own TLS via the do_connect listener, so the explicit
    SSL config must not also be injected as connect_args."""
    with patch.dict(os.environ, {}, clear=False):
        _clear_ssl_env()
        os.environ["USE_IAM_AUTH"] = "true"
        os.environ["POSTGRES_SSLMODE"] = "verify-full"
        module = _reload_pg_ssl()
        assert module.pg_ssl_psycopg2_connect_args() == {}


# --- asyncpg SSLContext ---------------------------------------------------


def test_asyncpg_none_when_unset_or_disabled() -> None:
    for mode in (None, "disable"):
        with patch.dict(os.environ, {}, clear=False):
            _clear_ssl_env()
            if mode:
                os.environ["POSTGRES_SSLMODE"] = mode
            module = _reload_pg_ssl()
            assert module.create_pg_ssl_context() is None


def test_asyncpg_prefer_passes_mode_string_through() -> None:
    """allow/prefer have no custom-CA semantics; asyncpg handles the
    opportunistic-with-fallback behavior natively from the mode string."""
    with patch.dict(os.environ, {}, clear=False):
        _clear_ssl_env()
        os.environ["POSTGRES_SSLMODE"] = "prefer"
        module = _reload_pg_ssl()
        assert module.create_pg_ssl_context() == "prefer"


def test_asyncpg_require_encrypts_without_verifying() -> None:
    with patch.dict(os.environ, {}, clear=False):
        _clear_ssl_env()
        os.environ["POSTGRES_SSLMODE"] = "require"
        module = _reload_pg_ssl()
        ctx = module.create_pg_ssl_context()
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.check_hostname is False
        assert ctx.verify_mode == ssl.CERT_NONE


def test_asyncpg_verify_ca_verifies_cert_not_hostname() -> None:
    with patch.dict(os.environ, {}, clear=False):
        _clear_ssl_env()
        os.environ["POSTGRES_SSLMODE"] = "verify-ca"
        os.environ["POSTGRES_SSLROOTCERT"] = _CA_BUNDLE
        module = _reload_pg_ssl()
        ctx = module.create_pg_ssl_context()
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.check_hostname is False
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.get_ca_certs(), "CA bundle should be loaded for verification"


def test_asyncpg_verify_full_verifies_cert_and_hostname() -> None:
    with patch.dict(os.environ, {}, clear=False):
        _clear_ssl_env()
        os.environ["POSTGRES_SSLMODE"] = "verify-full"
        os.environ["POSTGRES_SSLROOTCERT"] = _CA_BUNDLE
        module = _reload_pg_ssl()
        ctx = module.create_pg_ssl_context()
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.check_hostname is True
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.get_ca_certs(), "CA bundle should be loaded for verification"


def test_asyncpg_not_none_with_explicit_ssl_regression_guard() -> None:
    """Regression guard for the silent-plaintext footgun: when SSL is explicitly
    configured, the value handed to asyncpg's connect_args["ssl"] must not be
    None (which would otherwise drop the connection to plaintext)."""
    with patch.dict(os.environ, {}, clear=False):
        _clear_ssl_env()
        os.environ["POSTGRES_SSLMODE"] = "verify-full"
        os.environ["POSTGRES_SSLROOTCERT"] = _CA_BUNDLE
        module = _reload_pg_ssl()
        assert module.create_pg_ssl_context() is not None


# --- config validation ----------------------------------------------------


def test_invalid_sslmode_raises_at_config_import() -> None:
    with patch.dict(os.environ, {}, clear=False):
        _clear_ssl_env()
        os.environ["POSTGRES_SSLMODE"] = "bogus"
        import onyx.configs.app_configs as app_configs

        with pytest.raises(ValueError, match="Invalid POSTGRES_SSLMODE"):
            importlib.reload(app_configs)
    # restore a clean module for any later tests in the session
    importlib.reload(app_configs)


def test_verify_full_without_rootcert_raises() -> None:
    """verify-ca/verify-full must fail loudly without a CA bundle rather than
    silently fall back to the system trust store."""
    import onyx.configs.app_configs as app_configs

    for mode in ("verify-ca", "verify-full"):
        with patch.dict(os.environ, {}, clear=False):
            _clear_ssl_env()
            os.environ["POSTGRES_SSLMODE"] = mode
            with pytest.raises(ValueError, match="requires POSTGRES_SSLROOTCERT"):
                importlib.reload(app_configs)
    importlib.reload(app_configs)


def test_nonexistent_rootcert_raises() -> None:
    with patch.dict(os.environ, {}, clear=False):
        _clear_ssl_env()
        os.environ["POSTGRES_SSLMODE"] = "verify-full"
        os.environ["POSTGRES_SSLROOTCERT"] = "/no/such/ca-bundle.pem"
        import onyx.configs.app_configs as app_configs

        with pytest.raises(ValueError, match="does not exist"):
            importlib.reload(app_configs)
    importlib.reload(app_configs)


def test_invalid_sslmode_ignored_under_iam() -> None:
    """IAM enforces its own TLS, so an ignored (even invalid) POSTGRES_SSLMODE
    must not fail startup — validation is gated behind the non-IAM path."""
    with patch.dict(os.environ, {}, clear=False):
        _clear_ssl_env()
        os.environ["USE_IAM_AUTH"] = "true"
        os.environ["POSTGRES_SSLMODE"] = "bogus"
        import onyx.configs.app_configs as app_configs

        importlib.reload(app_configs)  # must NOT raise
        assert app_configs.USE_IAM_AUTH is True
    importlib.reload(app_configs)
