# Tool to run helpful operations on Redis in production
import argparse
import logging
import sys
import time
from logging import getLogger
from typing import cast

from redis import Redis

from onyx.redis.redis_pool import RedisPool

# Configure the logger
logging.basicConfig(
    level=logging.INFO,  # Set the log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",  # Log format
    handlers=[logging.StreamHandler()],  # Output logs to console
)

logger = getLogger(__name__)

REDIS_PASSWORD = ""


def onyx_redis(command: str) -> int:
    pool = RedisPool.create_pool(
        host="127.0.0.1",
        port=6380,
        password=REDIS_PASSWORD,
        ssl=True,
        ssl_cert_reqs="optional",
        ssl_ca_certs=None,
    )

    r = Redis(connection_pool=pool)

    if command == "purge_connectorsync":
        """Purge connector tasksets. Used when the tasks represented in the tasksets
        have been purged."""
        return purge_by_match_and_type("*connectorsync_taskset*", "set", r)

    return 255


def purge_by_match_and_type(match_pattern: str, match_type: str, r: Redis) -> int:
    """match_pattern: glob style expression
    match_type: https://redis.io/docs/latest/commands/type/
    """

    # cursor = "0"
    # while cursor != 0:
    #     cursor, data = self.scan(
    #         cursor=cursor, match=match, count=count, _type=_type, **kwargs
    #     )

    start = time.monotonic()

    count = 0
    for key in r.scan_iter(match_pattern, count=10000):
        key_type = r.type(key)
        if key_type != match_type.encode("utf-8"):
            continue

        key = cast(bytes, key)
        key_str = key.decode("utf-8")

        count += 1
        logger.info(f"Deleting item {count}: {key_str}")
        r.delete(key)

    logger.info(f"Found {count} matches.")

    elapsed = time.monotonic() - start
    logger.info(f"Time elapsed: {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Onyx Redis Tools")
    parser.add_argument("--command", type=str, help="Operation to run", required=True)

    args = parser.parse_args()
    exitcode = onyx_redis(command=args.command)
    sys.exit(exitcode)
