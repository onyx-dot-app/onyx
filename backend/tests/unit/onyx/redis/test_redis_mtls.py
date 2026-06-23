import importlib
import os
from pathlib import Path
from unittest.mock import patch

import pytest

import onyx.redis.redis_pool as redis_pool

_REDIS_TLS_ENV = (
    "REDIS_SSL",
    "REDIS_SSL_CERTFILE",
    "REDIS_SSL_KEYFILE",
    "REDIS_SSL_CA_CERTS",
    "USE_REDIS_IAM_AUTH",
)


def _clear_redis_tls_env() -> None:
    for var in _REDIS_TLS_ENV:
        os.environ.pop(var, None)


@pytest.fixture(autouse=True)
def _restore_app_configs() -> object:
    """Config-reload tests bind REDIS_SSL* at import time; restore the default
    state afterwards so they don't leak into other test files."""
    yield
    _clear_redis_tls_env()
    import onyx.configs.app_configs as app_configs

    importlib.reload(app_configs)


# --- connection wiring ----------------------------------------------------


def test_sync_pool_forwards_client_cert() -> None:
    """The sync pool must hand the client cert/key to redis-py — today only the
    CA + cert_reqs are passed."""
    with patch("redis.BlockingConnectionPool") as mock_pool:
        redis_pool.RedisPool.create_pool(
            ssl=True,
            ssl_certfile="/etc/redis/tls/client.crt",
            ssl_keyfile="/etc/redis/tls/client.key",
        )
        kwargs = mock_pool.call_args.kwargs
        assert kwargs["ssl_certfile"] == "/etc/redis/tls/client.crt"
        assert kwargs["ssl_keyfile"] == "/etc/redis/tls/client.key"


def test_async_connection_loads_client_cert() -> None:
    """The async client builds an SSLContext manually, so the client cert is
    applied via load_cert_chain."""
    with (
        patch.object(redis_pool, "USE_REDIS_IAM_AUTH", False),
        patch.object(redis_pool, "REDIS_SSL", True),
        patch.object(redis_pool, "REDIS_SSL_CA_CERTS", None),
        patch.object(redis_pool, "REDIS_SSL_CERTFILE", "/c.crt"),
        patch.object(redis_pool, "REDIS_SSL_KEYFILE", "/c.key"),
        patch.object(redis_pool, "ssl") as mock_ssl,
        patch.object(redis_pool, "aioredis"),
    ):
        redis_pool._build_async_redis_connection()
        ctx = mock_ssl.create_default_context.return_value
        ctx.load_cert_chain.assert_called_once_with("/c.crt", "/c.key")


def test_celery_broker_and_result_urls_include_client_cert(tmp_path: Path) -> None:
    cert = tmp_path / "client.crt"
    key = tmp_path / "client.key"
    cert.write_text("x")
    key.write_text("x")
    with patch.dict(os.environ, {}, clear=False):
        _clear_redis_tls_env()
        os.environ["REDIS_SSL"] = "true"
        os.environ["REDIS_SSL_CERTFILE"] = str(cert)
        os.environ["REDIS_SSL_KEYFILE"] = str(key)
        import onyx.background.celery.configs.base as celery_base
        import onyx.configs.app_configs as app_configs

        importlib.reload(app_configs)
        importlib.reload(celery_base)
        for url in (celery_base.broker_url, celery_base.result_backend):
            assert url.startswith("rediss://")
            assert f"ssl_certfile={cert}" in url
            assert f"ssl_keyfile={key}" in url
    importlib.reload(app_configs)


# --- config validation ----------------------------------------------------


def test_certfile_without_keyfile_raises(tmp_path: Path) -> None:
    cert = tmp_path / "client.crt"
    cert.write_text("x")
    with patch.dict(os.environ, {}, clear=False):
        _clear_redis_tls_env()
        os.environ["REDIS_SSL"] = "true"
        os.environ["REDIS_SSL_CERTFILE"] = str(cert)
        import onyx.configs.app_configs as app_configs

        with pytest.raises(ValueError, match="must both be set"):
            importlib.reload(app_configs)
    importlib.reload(app_configs)


def test_client_cert_without_redis_ssl_raises(tmp_path: Path) -> None:
    cert = tmp_path / "client.crt"
    key = tmp_path / "client.key"
    cert.write_text("x")
    key.write_text("x")
    with patch.dict(os.environ, {}, clear=False):
        _clear_redis_tls_env()
        os.environ["REDIS_SSL_CERTFILE"] = str(cert)
        os.environ["REDIS_SSL_KEYFILE"] = str(key)
        import onyx.configs.app_configs as app_configs

        with pytest.raises(ValueError, match="require REDIS_SSL=true"):
            importlib.reload(app_configs)
    importlib.reload(app_configs)


def test_nonexistent_certfile_raises() -> None:
    with patch.dict(os.environ, {}, clear=False):
        _clear_redis_tls_env()
        os.environ["REDIS_SSL"] = "true"
        os.environ["REDIS_SSL_CERTFILE"] = "/no/such/client.crt"
        os.environ["REDIS_SSL_KEYFILE"] = "/no/such/client.key"
        import onyx.configs.app_configs as app_configs

        with pytest.raises(ValueError, match="does not exist"):
            importlib.reload(app_configs)
    importlib.reload(app_configs)
