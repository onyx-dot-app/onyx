import os

import pytest
import redis

from onyx.redis.redis_pool import RedisPool
from onyx.utils.logger import setup_logger

logger = setup_logger()


@pytest.mark.skipif(
    os.getenv("REDIS_CLOUD_PYTEST_PASSWORD") is None,
    reason="Environment variable REDIS_CLOUD_PYTEST_PASSWORD is not set",
)
def test_redis_ssl() -> None:
    REDIS_PASSWORD = os.environ.get("REDIS_CLOUD_PYTEST_PASSWORD")
    REDIS_HOST = "redis-15414.c267.us-east-1-4.ec2.redns.redis-cloud.com"
    REDIS_PORT = 15414
    REDIS_SSL_CERT_REQS = "required"

    assert REDIS_PASSWORD

    # Construct the path to the CA certificate for the redis ssl test instance
    # it contains no secret data, so it's OK to have checked in!
    current_dir = os.path.dirname(__file__)
    REDIS_SSL_CA_CERTS = os.path.join(current_dir, "redis_ca.pem")

    pool = RedisPool.create_pool(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        ssl=True,
        ssl_cert_reqs=REDIS_SSL_CERT_REQS,
        ssl_ca_certs=REDIS_SSL_CA_CERTS,
    )

    r = redis.Redis(connection_pool=pool)
    assert r.ping()
