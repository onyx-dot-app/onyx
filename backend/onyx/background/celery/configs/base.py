# docs: https://docs.celeryq.dev/en/stable/userguide/configuration.html
import urllib.parse

from onyx.configs.app_configs import CELERY_BROKER_POOL_LIMIT
from onyx.configs.app_configs import CELERY_RESULT_EXPIRES
from onyx.configs.app_configs import REDIS_DB_NUMBER_CELERY
from onyx.configs.app_configs import REDIS_DB_NUMBER_CELERY_RESULT_BACKEND
from onyx.configs.app_configs import REDIS_HEALTH_CHECK_INTERVAL
from onyx.configs.app_configs import REDIS_HOST
from onyx.configs.app_configs import REDIS_PASSWORD
from onyx.configs.app_configs import REDIS_PORT
from onyx.configs.app_configs import REDIS_SENTINEL_HOSTS
from onyx.configs.app_configs import REDIS_SENTINEL_MASTER_NAME
from onyx.configs.app_configs import REDIS_SENTINEL_PASSWORD
from onyx.configs.app_configs import REDIS_SSL
from onyx.configs.app_configs import REDIS_SSL_CA_CERTS
from onyx.configs.app_configs import REDIS_SSL_CERT_REQS
from onyx.configs.app_configs import REDIS_SSL_CERTFILE
from onyx.configs.app_configs import REDIS_SSL_KEYFILE
from onyx.configs.app_configs import USE_REDIS_IAM_AUTH
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import REDIS_SOCKET_KEEPALIVE_OPTIONS

CELERY_SEPARATOR = ":"

CELERY_PASSWORD_PART = ""
if REDIS_PASSWORD:
    CELERY_PASSWORD_PART = ":" + urllib.parse.quote(REDIS_PASSWORD, safe="") + "@"

REDIS_SCHEME = "redis"

# SSL-specific query parameters for Redis URL
SSL_QUERY_PARAMS = ""
if REDIS_SSL and not USE_REDIS_IAM_AUTH:
    REDIS_SCHEME = "rediss"
    SSL_QUERY_PARAMS = f"?ssl_cert_reqs={REDIS_SSL_CERT_REQS}"
    if REDIS_SSL_CA_CERTS:
        SSL_QUERY_PARAMS += f"&ssl_ca_certs={REDIS_SSL_CA_CERTS}"
    # Client certificate for mutual TLS — the broker URL is how the Celery
    # workers get their Redis SSL config, so they need this too. Percent-encode
    # the paths (like REDIS_PASSWORD above) so URL-special characters in a path
    # can't corrupt the query string.
    if REDIS_SSL_CERTFILE and REDIS_SSL_KEYFILE:
        SSL_QUERY_PARAMS += (
            f"&ssl_certfile={urllib.parse.quote(REDIS_SSL_CERTFILE, safe='')}"
            f"&ssl_keyfile={urllib.parse.quote(REDIS_SSL_KEYFILE, safe='')}"
        )

# Redis Sentinel (HA): Celery/kombu use one `sentinel://` URL per node, the
# master name in transport options, and `broker_use_ssl` for TLS. The URL
# password authenticates the master/replica; sentinel-node auth + TLS go in
# `sentinel_kwargs`.
USE_SENTINEL = bool(REDIS_SENTINEL_HOSTS)
_SENTINEL_USE_SSL = REDIS_SSL and not USE_REDIS_IAM_AUTH


def _redis_ssl_settings() -> dict[str, str]:
    settings: dict[str, str] = {"ssl_cert_reqs": REDIS_SSL_CERT_REQS}
    if REDIS_SSL_CA_CERTS:
        settings["ssl_ca_certs"] = REDIS_SSL_CA_CERTS
    if REDIS_SSL_CERTFILE and REDIS_SSL_KEYFILE:
        settings["ssl_certfile"] = REDIS_SSL_CERTFILE
        settings["ssl_keyfile"] = REDIS_SSL_KEYFILE
    return settings


_SENTINEL_NODES = ";".join(
    f"sentinel://{CELERY_PASSWORD_PART}{host}:{port}"
    for host, port in REDIS_SENTINEL_HOSTS
)
_SENTINEL_TRANSPORT_OPTIONS: dict = {}
# Celery TLS settings for the Sentinel data connections. Always defined (empty =
# no SSL, matching Celery's default) so they're not conditionally-present module
# globals.
broker_use_ssl: dict[str, str] = {}
redis_backend_use_ssl: dict[str, str] = {}
if USE_SENTINEL:
    _SENTINEL_TRANSPORT_OPTIONS["master_name"] = REDIS_SENTINEL_MASTER_NAME
    _sentinel_kwargs: dict = {}
    if REDIS_SENTINEL_PASSWORD:
        _sentinel_kwargs["password"] = REDIS_SENTINEL_PASSWORD
    if _SENTINEL_USE_SSL:
        # sentinel_kwargs are redis-py connection kwargs, so they need the
        # explicit `ssl` flag to actually negotiate TLS (the cert settings are
        # inert without it). broker_use_ssl below is a Celery setting whose mere
        # presence enables TLS, so it must NOT carry the `ssl` key.
        _sentinel_kwargs.update(_redis_ssl_settings())
        _sentinel_kwargs["ssl"] = True
    if _sentinel_kwargs:
        _SENTINEL_TRANSPORT_OPTIONS["sentinel_kwargs"] = _sentinel_kwargs
    # TLS for the master/replica data connections.
    if _SENTINEL_USE_SSL:
        broker_use_ssl = _redis_ssl_settings()
        redis_backend_use_ssl = _redis_ssl_settings()

# region Broker settings
# example celery_broker_url: "redis://:password@localhost:6379/15"
if USE_SENTINEL:
    broker_url = f"{_SENTINEL_NODES}/{REDIS_DB_NUMBER_CELERY}"
else:
    broker_url = f"{REDIS_SCHEME}://{CELERY_PASSWORD_PART}{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB_NUMBER_CELERY}{SSL_QUERY_PARAMS}"

broker_connection_retry_on_startup = True
broker_pool_limit = CELERY_BROKER_POOL_LIMIT

# redis broker settings
# https://docs.celeryq.dev/projects/kombu/en/stable/reference/kombu.transport.redis.html
broker_transport_options = {
    "priority_steps": list(range(len(OnyxCeleryPriority))),
    "sep": CELERY_SEPARATOR,
    "queue_order_strategy": "priority",
    "retry_on_timeout": True,
    "health_check_interval": REDIS_HEALTH_CHECK_INTERVAL,
    "socket_keepalive": True,
    "socket_keepalive_options": REDIS_SOCKET_KEEPALIVE_OPTIONS,
}
if USE_SENTINEL:
    broker_transport_options.update(_SENTINEL_TRANSPORT_OPTIONS)
# endregion

# redis backend settings
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#redis-backend-settings

# there doesn't appear to be a way to set socket_keepalive_options on the redis result backend
redis_socket_keepalive = True
redis_retry_on_timeout = True
redis_backend_health_check_interval = REDIS_HEALTH_CHECK_INTERVAL


task_default_priority = OnyxCeleryPriority.MEDIUM
task_acks_late = True

# region Task result backend settings
# It's possible we don't even need celery's result backend, in which case all of the optimization below
# might be irrelevant
result_backend_transport_options: dict = {}
if USE_SENTINEL:
    result_backend = f"{_SENTINEL_NODES}/{REDIS_DB_NUMBER_CELERY_RESULT_BACKEND}"
    result_backend_transport_options = _SENTINEL_TRANSPORT_OPTIONS
else:
    result_backend = f"{REDIS_SCHEME}://{CELERY_PASSWORD_PART}{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB_NUMBER_CELERY_RESULT_BACKEND}{SSL_QUERY_PARAMS}"
result_expires = CELERY_RESULT_EXPIRES  # 86400 seconds is the default
# endregion

# Leaving this to the default of True may cause double logging since both our own app
# and celery think they are controlling the logger.
# TODO: Configure celery's logger entirely manually and set this to False
# worker_hijack_root_logger = False

# region Notes on serialization performance
# Option 0: Defaults (json serializer, no compression)
# about 1.5 KB per queued task. 1KB in queue, 400B for result, 100 as a child entry in generator result

# Option 1: Reduces generator task result sizes by roughly 20%
# task_compression = "bzip2"
# task_serializer = "pickle"
# result_compression = "bzip2"
# result_serializer = "pickle"
# accept_content=["pickle"]

# Option 2: this significantly reduces the size of the result for generator tasks since the list of children
# can be large. small tasks change very little
# def pickle_bz2_encoder(data):
#     return bz2.compress(pickle.dumps(data))

# def pickle_bz2_decoder(data):
#     return pickle.loads(bz2.decompress(data))

# from kombu import serialization  # To register custom serialization with Celery/Kombu

# serialization.register('pickle-bzip2', pickle_bz2_encoder, pickle_bz2_decoder, 'application/x-pickle-bz2', 'binary')

# task_serializer = "pickle-bzip2"
# result_serializer = "pickle-bzip2"
# accept_content=["pickle", "pickle-bzip2"]
# endregion
