import importlib
import os
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

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
def _restore_app_configs() -> Generator[None, None, None]:
    """Config-reload tests bind REDIS_SSL* at import time; restore the default
    state afterwards so they don't leak into other test files. celery_base is
    reloaded too since it derives broker_url / result_backend from those."""
    yield
    _clear_redis_tls_env()
    import onyx.configs.app_configs as app_configs

    importlib.reload(app_configs)
    import onyx.background.celery.configs.base as celery_base

    importlib.reload(celery_base)


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


def test_async_connection_passes_native_ssl_kwargs() -> None:
    """The async client must get redis-py's native ssl_* kwargs — it ignores a
    prebuilt ssl_context, so the client cert / CA have to flow through these."""
    with (
        patch.object(redis_pool, "USE_REDIS_IAM_AUTH", False),
        patch.object(redis_pool, "REDIS_SSL", True),
        patch.object(redis_pool, "REDIS_SSL_CA_CERTS", "/ca.crt"),
        patch.object(redis_pool, "REDIS_SSL_CERT_REQS", "required"),
        patch.object(redis_pool, "REDIS_SSL_CERTFILE", "/c.crt"),
        patch.object(redis_pool, "REDIS_SSL_KEYFILE", "/c.key"),
        patch.object(redis_pool, "aioredis") as mock_aioredis,
    ):
        redis_pool._build_async_redis_connection()
        kwargs = mock_aioredis.Redis.call_args.kwargs
        assert kwargs["ssl"] is True
        assert kwargs["ssl_cert_reqs"] == "required"
        assert kwargs["ssl_check_hostname"] is False
        assert kwargs["ssl_ca_certs"] == "/ca.crt"
        assert kwargs["ssl_certfile"] == "/c.crt"
        assert kwargs["ssl_keyfile"] == "/c.key"
        assert "ssl_context" not in kwargs


def test_iam_auth_uses_native_async_ssl_kwargs() -> None:
    """The async IAM path must use native ssl_* kwargs, not ssl_context — the
    async Redis client rejects ssl_context with a TypeError, so passing one
    crashes every async IAM connection."""
    import redis.asyncio as aioredis

    from onyx.redis.iam_auth import configure_redis_iam_auth

    kwargs: dict = {"host": "h", "port": 6379, "password": "pw"}
    configure_redis_iam_auth(kwargs)
    assert "ssl_context" not in kwargs
    assert "password" not in kwargs  # IAM drops the password
    assert kwargs["ssl"] is True
    assert kwargs["ssl_cert_reqs"] == "required"
    assert kwargs["ssl_check_hostname"] is True
    # Regression guard: constructing the async client must not raise the
    # "unexpected keyword argument 'ssl_context'" TypeError.
    aioredis.Redis(**kwargs)


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
        # Paths are percent-encoded in the URL (safe='') so special characters
        # can't corrupt the query string.
        enc_cert = quote(str(cert), safe="")
        enc_key = quote(str(key), safe="")
        for url in (celery_base.broker_url, celery_base.result_backend):
            assert url.startswith("rediss://")
            assert f"ssl_certfile={enc_cert}" in url
            assert f"ssl_keyfile={enc_key}" in url


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
