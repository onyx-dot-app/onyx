import importlib
import os
from types import ModuleType
from unittest.mock import patch


def _reload_app_configs() -> ModuleType:
    """Reload the module so the env var is re-read at import time."""
    import onyx.configs.app_configs as module

    return importlib.reload(module)


def test_postgres_pool_pre_ping_defaults_to_true() -> None:
    """Default should be True — pre-pings pooled connections at checkout to
    survive PgBouncer / Postgres dropping idle connections. Preventing
    `psycopg2.OperationalError: server closed the connection unexpectedly`."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("POSTGRES_POOL_PRE_PING", None)
        module = _reload_app_configs()
        assert module.POSTGRES_POOL_PRE_PING is True


def test_postgres_pool_pre_ping_can_be_disabled() -> None:
    """Explicit `POSTGRES_POOL_PRE_PING=false` still opts out."""
    with patch.dict(os.environ, {"POSTGRES_POOL_PRE_PING": "false"}):
        module = _reload_app_configs()
        assert module.POSTGRES_POOL_PRE_PING is False


def test_postgres_pool_pre_ping_case_insensitive_true() -> None:
    """Explicit `POSTGRES_POOL_PRE_PING=TRUE` is recognised."""
    with patch.dict(os.environ, {"POSTGRES_POOL_PRE_PING": "TRUE"}):
        module = _reload_app_configs()
        assert module.POSTGRES_POOL_PRE_PING is True
