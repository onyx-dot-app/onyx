#!/usr/bin/env python3

import argparse
import subprocess
import time

from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger

logger = setup_logger()

MAX_AGE_SECONDS = 900  # how old the heartbeat can be
CHECK_INTERVAL = 60  # how often to check
MAX_LOOKUP_FAILURES = 5


def main(key: str, program: str, conf: str) -> None:
    """This script will restart the watchdog'd supervisord process via supervisorctl.

    This process continually looks up a specific redis key. If it is missing for a
    consecutive number of times and the last successful lookup is more
    than a threshold time, the specified program will be restarted.
    """
    logger.info("supervisord_watchdog starting: program=%s conf=%s", program, conf)

    r = get_redis_client()

    last_heartbeat = time.monotonic()
    num_lookup_failures = 0

    try:
        while True:
            time.sleep(CHECK_INTERVAL)

            now = time.monotonic()

            # check for the key ... handle any exception gracefully
            try:
                heartbeat = r.exists(key)
            except Exception:
                logger.exception(
                    "Exception checking for celery beat heartbeat: key=%s.", key
                )
                continue

            # happy path ... just continue
            if heartbeat:
                logger.debug("Key lookup succeeded: key=%s", key)
                last_heartbeat = time.monotonic()
                num_lookup_failures = 0
                continue

            # if we haven't exceeded the max lookup failures, continue
            num_lookup_failures += 1
            if num_lookup_failures <= MAX_LOOKUP_FAILURES:
                logger.warning(
                    "Key lookup failed: key=%s lookup_failures=%s max_lookup_failures=%s",
                    key,
                    num_lookup_failures,
                    MAX_LOOKUP_FAILURES,
                )
                continue

            # if we haven't exceeded the max missing key timeout threshold, continue
            elapsed = now - last_heartbeat
            if elapsed <= MAX_AGE_SECONDS:
                logger.warning(
                    "Key lookup failed: key=%s lookup_failures=%s max_lookup_failures=%s elapsed=%s elapsed_threshold=%s",
                    key,
                    num_lookup_failures,
                    MAX_LOOKUP_FAILURES,
                    format(elapsed, ".2f"),
                    MAX_AGE_SECONDS,
                )
                continue

            # all conditions have been exceeded ... restart the process
            logger.warning(
                "Key lookup failure thresholds exceeded - restarting %s: key=%s lookup_failures=%s max_lookup_failures=%s elapsed=%s elapsed_threshold=%s",
                program,
                key,
                num_lookup_failures,
                MAX_LOOKUP_FAILURES,
                format(elapsed, ".2f"),
                MAX_AGE_SECONDS,
            )

            subprocess.call(["supervisorctl", "-c", conf, "restart", program])

            # reset state so that we properly delay until the next restart
            # instead of continually restarting
            num_lookup_failures = 0
            last_heartbeat = time.monotonic()
    except KeyboardInterrupt:
        logger.info("Caught interrupt, exiting watchdog.")

    logger.info("supervisord_watchdog exiting.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Supervisord Watchdog")
    parser.add_argument("--key", help="The redis key to watch", required=True)
    parser.add_argument(
        "--program", help="The supervisord program to restart", required=True
    )
    parser.add_argument(
        "--conf", type=str, help="Path to supervisord config file", required=True
    )
    args = parser.parse_args()

    main(args.key, args.program, args.conf)
