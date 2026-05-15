import importlib
import os
from types import ModuleType
from unittest.mock import patch


def _reload_app_configs() -> ModuleType:
    """Reload the module so the env vars are re-read at import time."""
    import onyx.configs.app_configs as module

    return importlib.reload(module)


def _reload_sql_engine() -> ModuleType:
    """Reload sql_engine after app_configs has been reloaded so it picks up
    the freshly parsed constants. Required because sql_engine binds them at
    import time."""
    _reload_app_configs()
    import onyx.db.engine.sql_engine as module

    return importlib.reload(module)


def test_postgres_tcp_keepalives_defaults_to_enabled() -> None:
    """Defaults should mirror the values documented in app_configs.py and
    produce the libpq connect-arg dict that psycopg2 expects."""
    with patch.dict(os.environ, {}, clear=False):
        for var in (
            "POSTGRES_TCP_KEEPALIVES",
            "POSTGRES_TCP_KEEPALIVES_IDLE",
            "POSTGRES_TCP_KEEPALIVES_INTERVAL",
            "POSTGRES_TCP_KEEPALIVES_COUNT",
        ):
            os.environ.pop(var, None)
        module = _reload_sql_engine()
        assert module.psycopg2_keepalive_connect_args() == {
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
        }


def test_postgres_tcp_keepalives_can_be_disabled() -> None:
    """`POSTGRES_TCP_KEEPALIVES=false` returns an empty dict so the engine
    falls back to libpq's default (keepalives off)."""
    with patch.dict(os.environ, {"POSTGRES_TCP_KEEPALIVES": "false"}):
        module = _reload_sql_engine()
        assert module.psycopg2_keepalive_connect_args() == {}


def test_postgres_tcp_keepalives_respects_overrides() -> None:
    """Custom values flow through to the libpq connect_args dict."""
    with patch.dict(
        os.environ,
        {
            "POSTGRES_TCP_KEEPALIVES": "true",
            "POSTGRES_TCP_KEEPALIVES_IDLE": "15",
            "POSTGRES_TCP_KEEPALIVES_INTERVAL": "5",
            "POSTGRES_TCP_KEEPALIVES_COUNT": "3",
        },
    ):
        module = _reload_sql_engine()
        assert module.psycopg2_keepalive_connect_args() == {
            "keepalives": 1,
            "keepalives_idle": 15,
            "keepalives_interval": 5,
            "keepalives_count": 3,
        }


def test_merge_psycopg2_connect_args_caller_wins() -> None:
    """A caller passing `connect_args` to `init_engine` should win on key
    conflicts but inherit the keepalive defaults for any keys it omits."""
    with patch.dict(os.environ, {}, clear=False):
        for var in (
            "POSTGRES_TCP_KEEPALIVES",
            "POSTGRES_TCP_KEEPALIVES_IDLE",
            "POSTGRES_TCP_KEEPALIVES_INTERVAL",
            "POSTGRES_TCP_KEEPALIVES_COUNT",
        ):
            os.environ.pop(var, None)
        module = _reload_sql_engine()
        extra = {"connect_args": {"keepalives_idle": 5, "sslmode": "require"}}
        merged = module._merge_psycopg2_connect_args(extra)
        assert "connect_args" not in extra, (
            "caller's connect_args must be popped so the .update() below "
            "doesn't overwrite the merged dict"
        )
        assert merged == {
            "keepalives": 1,
            "keepalives_idle": 5,
            "keepalives_interval": 10,
            "keepalives_count": 5,
            "sslmode": "require",
        }


def test_merge_psycopg2_connect_args_returns_none_when_empty() -> None:
    """If keepalives are off and the caller didn't pass connect_args, the
    helper returns None so the engine init can skip setting it entirely."""
    with patch.dict(os.environ, {"POSTGRES_TCP_KEEPALIVES": "false"}):
        module = _reload_sql_engine()
        assert module._merge_psycopg2_connect_args({}) is None
