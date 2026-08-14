import importlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast
from unittest.mock import patch

import onyx.redis.redis_pool as redis_pool

_SENTINELS = [("s1", 26379), ("s2", 26379)]


# --- app Redis (sync + async) connection routing --------------------------


def test_sync_create_pool_routes_through_sentinel_master() -> None:
    with (
        patch.object(redis_pool, "REDIS_SENTINEL_HOSTS", _SENTINELS),
        patch.object(redis_pool, "REDIS_SENTINEL_MASTER_NAME", "mymaster"),
        patch.object(redis_pool, "REDIS_SSL", False),
        patch.object(redis_pool, "Sentinel") as mock_sentinel_cls,
    ):
        pool = redis_pool.RedisPool.create_pool(db=5, replica=False)
        # built a Sentinel over the configured nodes
        assert mock_sentinel_cls.call_args.args[0] == _SENTINELS
        sentinel = mock_sentinel_cls.return_value
        sentinel.master_for.assert_called_once()
        assert sentinel.master_for.call_args.args[0] == "mymaster"
        sentinel.slave_for.assert_not_called()
        # returns the master client's connection pool (plugs into redis.Redis)
        assert pool is sentinel.master_for.return_value.connection_pool


def test_sync_create_pool_replica_uses_slave() -> None:
    with (
        patch.object(redis_pool, "REDIS_SENTINEL_HOSTS", _SENTINELS),
        patch.object(redis_pool, "REDIS_SSL", False),
        patch.object(redis_pool, "Sentinel") as mock_sentinel_cls,
    ):
        redis_pool.RedisPool.create_pool(replica=True)
        sentinel = mock_sentinel_cls.return_value
        sentinel.slave_for.assert_called_once()
        sentinel.master_for.assert_not_called()


def test_async_connection_routes_through_sentinel_master() -> None:
    with (
        patch.object(redis_pool, "REDIS_SENTINEL_HOSTS", _SENTINELS),
        patch.object(redis_pool, "REDIS_SENTINEL_MASTER_NAME", "mymaster"),
        patch.object(redis_pool, "REDIS_SSL", False),
        patch.object(redis_pool, "AsyncSentinel") as mock_async_sentinel_cls,
    ):
        conn = redis_pool._build_async_redis_connection()
        assert mock_async_sentinel_cls.call_args.args[0] == _SENTINELS
        sentinel = mock_async_sentinel_cls.return_value
        sentinel.master_for.assert_called_once()
        assert sentinel.master_for.call_args.args[0] == "mymaster"
        assert conn is sentinel.master_for.return_value


# --- TLS + auth applied to both sentinel and data connections -------------


def test_sentinel_tls_and_auth_apply_to_both_connection_sets() -> None:
    with (
        patch.object(redis_pool, "REDIS_SSL", True),
        patch.object(redis_pool, "REDIS_SSL_CERT_REQS", "required"),
        patch.object(redis_pool, "REDIS_SSL_CA_CERTS", "/ca.crt"),
        patch.object(redis_pool, "REDIS_SSL_CERTFILE", "/c.crt"),
        patch.object(redis_pool, "REDIS_SSL_KEYFILE", "/c.key"),
        patch.object(redis_pool, "REDIS_PASSWORD", "datapw"),
        patch.object(redis_pool, "REDIS_SENTINEL_PASSWORD", "sentinelpw"),
    ):
        connection_kwargs, sentinel_kwargs = redis_pool._sentinel_connection_kwargs()
        # data (master/replica) connections: master auth + TLS
        assert connection_kwargs["password"] == "datapw"
        assert connection_kwargs["ssl"] is True
        assert connection_kwargs["ssl_ca_certs"] == "/ca.crt"
        assert connection_kwargs["ssl_certfile"] == "/c.crt"
        # sentinel-node connections: sentinel auth + TLS
        assert sentinel_kwargs["password"] == "sentinelpw"
        assert sentinel_kwargs["ssl"] is True
        assert sentinel_kwargs["ssl_ca_certs"] == "/ca.crt"


# --- Celery broker / result backend ---------------------------------------

# Celery reads settings as attributes of the module given to
# `config_from_object`. A setting that base.py defines but a per-app module
# does not re-export falls back to the Celery default, silently.
_APP_CONFIG_MODULES = [
    f"onyx.background.celery.configs.{name}"
    for name in (
        "beat",
        "client",
        "docfetching",
        "docprocessing",
        "heavy",
        "light",
        "monitoring",
        "primary",
        "scheduled_tasks",
        "user_file_processing",
    )
]


def _reload_celery_configs() -> None:
    import onyx.background.celery.configs.base as celery_base
    import onyx.configs.app_configs as app_configs

    importlib.reload(app_configs)
    importlib.reload(celery_base)
    for module_name in _APP_CONFIG_MODULES:
        importlib.reload(importlib.import_module(module_name))


@contextmanager
def _celery_config_env(env: dict[str, str]) -> Iterator[None]:
    """Reload the Celery config modules under `env`, then restore them.

    The restore runs outside the env patch on purpose. These modules read
    os.environ as they execute, so reloading while it is still patched would
    leave the Sentinel settings in place for every later test.
    """
    try:
        with patch.dict(os.environ, env):
            _reload_celery_configs()
            yield
    finally:
        _reload_celery_configs()


def test_celery_uses_sentinel_urls_and_master_name() -> None:
    env = {
        "REDIS_SENTINEL_HOSTS": "s1:26379,s2:26379",
        "REDIS_SENTINEL_MASTER_NAME": "mymaster",
    }
    with _celery_config_env(env):
        import onyx.background.celery.configs.base as celery_base

        # the db goes on every node, not just the last one
        assert celery_base.broker_url == (
            "sentinel://s1:26379/15;sentinel://s2:26379/15"
        )
        assert celery_base.result_backend == (
            "sentinel://s1:26379/14;sentinel://s2:26379/14"
        )
        assert celery_base.broker_transport_options["master_name"] == "mymaster"
        assert celery_base.result_backend_transport_options["master_name"] == "mymaster"


# --- per-app Celery config modules ----------------------------------------

# Redis connection settings that every app must share with base.py.
_SHARED_CONNECTION_SETTINGS = [
    "broker_url",
    "broker_connection_retry_on_startup",
    "broker_pool_limit",
    "broker_transport_options",
    "broker_use_ssl",
    "redis_socket_keepalive",
    "redis_retry_on_timeout",
    "redis_backend_health_check_interval",
    "redis_backend_use_ssl",
    "result_backend",
    "result_backend_transport_options",
    "result_expires",
]


def test_app_configs_reexport_all_shared_connection_settings() -> None:
    import onyx.background.celery.configs.base as celery_base

    # normalize first: this assertion holds for any env, but only if base and
    # the app modules were last loaded under the same one
    _reload_celery_configs()

    for module_name in _APP_CONFIG_MODULES:
        module = importlib.import_module(module_name)
        for setting in _SHARED_CONNECTION_SETTINGS:
            assert hasattr(module, setting), f"{module_name} does not set {setting}"
            assert getattr(module, setting) == getattr(celery_base, setting), (
                f"{module_name} {setting} does not match base"
            )


def test_every_app_resolves_sentinel_master_name_on_both_connections() -> None:
    """Beat failed with "No master found for None" because the app config
    modules re-exported result_backend but not its transport options."""
    from celery import Celery

    env = {
        "REDIS_SENTINEL_HOSTS": "s1:26379,s2:26379",
        "REDIS_SENTINEL_MASTER_NAME": "mymaster",
        "REDIS_SENTINEL_PASSWORD": "sentinelpw",
    }
    with _celery_config_env(env):
        for module_name in _APP_CONFIG_MODULES:
            module = importlib.import_module(module_name)
            app = Celery(f"test-{module_name}")
            app.config_from_object(module)

            broker_options = cast(dict, app.conf["broker_transport_options"])
            backend_options = cast(dict, app.conf["result_backend_transport_options"])
            assert broker_options["master_name"] == "mymaster", (
                f"{module_name} broker lost the master name"
            )
            assert backend_options["master_name"] == "mymaster", (
                f"{module_name} result backend lost the master name"
            )
            assert backend_options["sentinel_kwargs"] == {"password": "sentinelpw"}, (
                f"{module_name} result backend lost the sentinel password"
            )


def test_sentinel_urls_keep_the_configured_redis_db() -> None:
    """Celery and kombu both read the db from the first node in the list. A db
    on the last node only sent the broker, the result backend, and the app
    itself all into db 0."""
    from celery import Celery
    from celery.backends.redis import SentinelBackend
    from kombu import Connection

    env = {
        "REDIS_SENTINEL_HOSTS": "s1:26379,s2:26379,s3:26379",
        "REDIS_SENTINEL_MASTER_NAME": "mymaster",
        "REDIS_PASSWORD": "datapw",
    }
    with _celery_config_env(env):
        import onyx.configs.app_configs as app_configs

        beat = importlib.import_module("onyx.background.celery.configs.beat")
        app = Celery("test-sentinel-db")
        app.config_from_object(beat)

        # kombu takes the db from the primary URL. It read "/" (-> db 0) while
        # the db sat on the last node.
        broker = Connection(
            app.conf["broker_url"],
            transport_options=app.conf["broker_transport_options"],
        )
        assert broker.virtual_host == str(app_configs.REDIS_DB_NUMBER_CELERY)

        backend = SentinelBackend(app=app, url=app.conf["result_backend"])
        connparams = cast(dict, backend.connparams)  # ty: ignore[unresolved-attribute]
        assert connparams["db"] == app_configs.REDIS_DB_NUMBER_CELERY_RESULT_BACKEND
        # master auth still rides the URL, and every node is discovered
        assert connparams["password"] == "datapw"
        assert len(connparams["hosts"]) == 3


# --- config validation + Celery TLS ---------------------------------------


def test_malformed_sentinel_hosts_raises() -> None:
    import pytest

    with patch.dict(os.environ, {"REDIS_SENTINEL_HOSTS": "no-port-here"}):
        import onyx.configs.app_configs as app_configs

        with pytest.raises(ValueError, match="expected host:port"):
            importlib.reload(app_configs)
    importlib.reload(app_configs)


def test_sentinel_with_iam_auth_raises() -> None:
    import pytest

    env = {"REDIS_SENTINEL_HOSTS": "s1:26379", "USE_REDIS_IAM_AUTH": "true"}
    with patch.dict(os.environ, env):
        import onyx.configs.app_configs as app_configs

        with pytest.raises(ValueError, match="cannot be combined"):
            importlib.reload(app_configs)
    importlib.reload(app_configs)


def test_celery_sentinel_kwargs_enable_ssl_under_tls() -> None:
    env = {"REDIS_SENTINEL_HOSTS": "s1:26379", "REDIS_SSL": "true"}
    with _celery_config_env(env):
        import onyx.background.celery.configs.base as celery_base

        sk = cast(dict, celery_base.broker_transport_options["sentinel_kwargs"])
        # cert params are inert without the explicit ssl flag
        assert sk["ssl"] is True
        # broker_use_ssl is a Celery setting; its presence enables TLS and it
        # must NOT carry the ssl key
        assert "ssl" not in celery_base.broker_use_ssl


def test_out_of_range_sentinel_port_raises() -> None:
    import pytest

    with patch.dict(os.environ, {"REDIS_SENTINEL_HOSTS": "s1:99999"}):
        import onyx.configs.app_configs as app_configs

        with pytest.raises(ValueError, match="must be 1-65535"):
            importlib.reload(app_configs)
    importlib.reload(app_configs)


def test_whitespace_master_name_raises() -> None:
    import pytest

    env = {"REDIS_SENTINEL_HOSTS": "s1:26379", "REDIS_SENTINEL_MASTER_NAME": "   "}
    with patch.dict(os.environ, env):
        import onyx.configs.app_configs as app_configs

        with pytest.raises(ValueError, match="MASTER_NAME is empty"):
            importlib.reload(app_configs)
    importlib.reload(app_configs)
