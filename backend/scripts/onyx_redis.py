# Tool to run helpful operations on Redis in production
# This is targeted for internal usage and may not have all the necessary parameters
# for general usage across custom deployments
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

SCAN_ITER_COUNT = 10000
BATCH_DEFAULT = 1000


def onyx_redis(
    command: str, batch: int, dry_run: bool, host: str, port: int, password: str | None
) -> int:
    pool = RedisPool.create_pool(
        host=host,
        port=port,
        password=password if password else "",
        ssl=True,
        ssl_cert_reqs="optional",
        ssl_ca_certs=None,
    )

    r = Redis(connection_pool=pool)

    try:
        r.ping()
    except:
        logger.exception("Redis ping exceptioned")
        raise

    if command == "purge_connectorsync_taskset":
        """Purge connector tasksets. Used when the tasks represented in the tasksets
        have been purged."""
        return purge_by_match_and_type(
            "*connectorsync_taskset*", "set", batch, dry_run, r
        )
    elif command == "purge_documentset_taskset":
        return purge_by_match_and_type(
            "*documentset_taskset*", "set", batch, dry_run, r
        )
    elif command == "purge_usergroup_taskset":
        return purge_by_match_and_type("*usergroup_taskset*", "set", batch, dry_run, r)
    elif command == "purge_vespa_syncing":
        return purge_by_match_and_type(
            "*connectorsync:vespa_syncing*", "string", batch, dry_run, r
        )
    else:
        pass

    return 255


def flush_batch_delete(batch_keys: list[bytes], r: Redis) -> None:
    logger.info(f"Flushing {len(batch_keys)} operations to Redis.")
    with r.pipeline() as pipe:
        for batch_key in batch_keys:
            pipe.delete(batch_key)
        pipe.execute()


def purge_by_match_and_type(
    match_pattern: str, match_type: str, batch_size: int, dry_run: bool, r: Redis
) -> int:
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
    batch_keys: list[bytes] = []
    for key in r.scan_iter(match_pattern, count=SCAN_ITER_COUNT, _type=match_type):
        # key_type = r.type(key)
        # if key_type != match_type.encode("utf-8"):
        #     continue

        key = cast(bytes, key)
        key_str = key.decode("utf-8")

        count += 1
        if dry_run:
            logger.info(f"(DRY-RUN) Deleting item {count}: {key_str}")
            continue

        logger.info(f"Deleting item {count}: {key_str}")

        batch_keys.append(key)
        if len(batch_keys) >= batch_size:
            flush_batch_delete(batch_keys, r)
            batch_keys.clear()

    if len(batch_keys) >= batch_size:
        flush_batch_delete(batch_keys, r)
        batch_keys.clear()

    logger.info(f"Deleted {count} matches.")

    elapsed = time.monotonic() - start
    logger.info(f"Time elapsed: {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Onyx Redis Manager")
    parser.add_argument("--command", type=str, help="Operation to run", required=True)

    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="The redis host",
        required=False,
    )

    parser.add_argument(
        "--port",
        type=int,
        default="6380",
        help="The redis port",
        required=False,
    )

    parser.add_argument(
        "--password",
        type=str,
        default=None,
        help="The redis password",
        required=False,
    )

    parser.add_argument(
        "--batch",
        type=int,
        default=BATCH_DEFAULT,
        help="Size of operation batches to send to Redis",
        required=False,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform a dry run without actually executing modifications",
        required=False,
    )

    args = parser.parse_args()
    exitcode = onyx_redis(
        command=args.command,
        batch=args.batch,
        dry_run=args.dry_run,
        host=args.host,
        port=args.port,
        password=args.password,
    )
    sys.exit(exitcode)
