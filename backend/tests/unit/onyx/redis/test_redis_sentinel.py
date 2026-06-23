import importlib
import os
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


def test_celery_uses_sentinel_urls_and_master_name() -> None:
    env = {
        "REDIS_SENTINEL_HOSTS": "s1:26379,s2:26379",
        "REDIS_SENTINEL_MASTER_NAME": "mymaster",
    }
    with patch.dict(os.environ, env):
        import onyx.background.celery.configs.base as celery_base
        import onyx.configs.app_configs as app_configs

        importlib.reload(app_configs)
        importlib.reload(celery_base)
        try:
            assert celery_base.broker_url == (
                "sentinel://s1:26379;sentinel://s2:26379/15"
            )
            assert celery_base.result_backend.startswith(
                "sentinel://s1:26379;sentinel://s2:26379/"
            )
            assert celery_base.broker_transport_options["master_name"] == "mymaster"
            assert (
                celery_base.result_backend_transport_options["master_name"]
                == "mymaster"
            )
        finally:
            importlib.reload(app_configs)
            importlib.reload(celery_base)


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
    with patch.dict(os.environ, env):
        import onyx.background.celery.configs.base as celery_base
        import onyx.configs.app_configs as app_configs

        importlib.reload(app_configs)
        importlib.reload(celery_base)
        try:
            sk = cast(dict, celery_base.broker_transport_options["sentinel_kwargs"])
            # cert params are inert without the explicit ssl flag
            assert sk["ssl"] is True
            # broker_use_ssl is a Celery setting; its presence enables TLS and it
            # must NOT carry the ssl key
            assert "ssl" not in celery_base.broker_use_ssl
        finally:
            importlib.reload(app_configs)
            importlib.reload(celery_base)


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
