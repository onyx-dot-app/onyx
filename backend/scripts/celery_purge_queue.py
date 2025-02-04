# Tool to run operations on Celery/Redis in production
# this is a work in progress and isn't completely put together yet
# but can serve as a stub for future operations
import argparse
import logging
from logging import getLogger

from redis import Redis

from onyx.background.celery.celery_redis import celery_get_queue_length
from onyx.configs.app_configs import REDIS_DB_NUMBER_CELERY
from onyx.redis.redis_pool import RedisPool

# Configure the logger
logging.basicConfig(
    level=logging.INFO,  # Set the log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",  # Log format
    handlers=[logging.StreamHandler()],  # Output logs to console
)

logger = getLogger(__name__)

REDIS_PASSWORD = ""


def celery_purge_queue(queue: str, tenant_id: str) -> None:
    """Purging a celery queue is extremely difficult because the queue is a list
    and the only way an item can be removed from a list is by VALUE, which is
    a linear scan.  Therefore, to purge the list of many values is roughly
    n^2.

    The other alternative is to pop values and push them back, but that raises
    questions about behavior while operating on a live queue.
    """

    pool = RedisPool.create_pool(
        host="127.0.0.1",
        port=6380,
        db=REDIS_DB_NUMBER_CELERY,
        password=REDIS_PASSWORD,
        ssl=True,
        ssl_cert_reqs="optional",
        ssl_ca_certs=None,
    )

    r = Redis(connection_pool=pool)

    length = celery_get_queue_length(queue, r)

    logger.info(f"queue={queue} length={length}")

    # processed = 0
    # deleted = 0
    # for i in range(len(OnyxCeleryPriority)):
    #     queue_name = queue
    #     if i > 0:
    #         queue_name += CELERY_SEPARATOR
    #         queue_name += str(i)

    #     length = r.llen(queue_name)
    #     for i in range(length):
    #         task_raw: bytes | None = r.lindex(queue_name, i)
    #         if not task_raw:
    #             break

    #         processed += 1
    #         task_str = task_raw.decode("utf-8")
    #         task = json.loads(task_str)
    #         task_kwargs_str = task["headers"]["kwargsrepr"]
    #         task_kwargs = json.loads(task_kwargs_str)
    #         task_tenant_id = task_kwargs["tenant_id"]
    #         if task_tenant_id and task_tenant_id == "tenant_id":
    #             print("Delete tenant_id={tenant_id}")
    #             if
    #             deleted += 1

    #         logger.info(f"processed={processed} deleted={deleted}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Purge celery queue by tenant id")
    parser.add_argument("--queue", type=str, help="Queue to purge", required=True)

    parser.add_argument("--tenant", type=str, help="Tenant ID to purge", required=True)

    args = parser.parse_args()
    celery_purge_queue(queue=args.queue, tenant_id=args.tenant)
