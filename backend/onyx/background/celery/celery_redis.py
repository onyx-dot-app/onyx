# These are helper objects for tracking the keys we need to write in redis
import json
import threading
from typing import Any, cast

from celery import Celery
from redis import Redis

from onyx.background.celery.configs.base import CELERY_SEPARATOR
from onyx.configs.app_configs import (
    REDIS_HEALTH_CHECK_INTERVAL,
    REDIS_SOCKET_TIMEOUT_KWARGS,
)
from onyx.configs.constants import REDIS_SOCKET_KEEPALIVE_OPTIONS, OnyxCeleryPriority

_broker_client: Redis | None = None
_broker_url: str | None = None
_broker_client_lock = threading.Lock()


def celery_get_broker_client(app: Celery) -> Redis:
    """Return a shared Redis client connected to the Celery broker DB.

    Uses a module-level singleton so all tasks on a worker share one
    connection instead of creating a new one per call. The client
    connects directly to the broker Redis DB (parsed from the broker URL).

    Thread-safe via lock — safe for use in Celery thread-pool workers.

    Usage:
        r_celery = celery_get_broker_client(self.app)
        length = celery_get_queue_length(queue, r_celery)
    """
    global _broker_client, _broker_url
    with _broker_client_lock:
        url = app.conf.broker_url
        if _broker_client is not None and _broker_url == url:
            try:
                _broker_client.ping()
                return _broker_client
            except Exception:
                try:
                    _broker_client.close()
                except Exception:
                    pass
                _broker_client = None
        elif _broker_client is not None:
            try:
                _broker_client.close()
            except Exception:
                pass
            _broker_client = None

        _broker_url = url
        _broker_client = Redis.from_url(
            url,
            decode_responses=False,
            health_check_interval=REDIS_HEALTH_CHECK_INTERVAL,
            socket_keepalive=True,
            socket_keepalive_options=REDIS_SOCKET_KEEPALIVE_OPTIONS,
            retry_on_timeout=True,
            **REDIS_SOCKET_TIMEOUT_KWARGS,
        )
        return _broker_client


def celery_get_unacked_task_ids(queue: str, r: Redis) -> set[str]:
    """Gets the set of task id's matching the given queue in the unacked hash.

    Unacked entries belonging to the indexing queues are "prefetched", so this gives
    us crucial visibility as to what tasks are in that state.

    Uses a bytes-substring pre-filter to skip the json.loads call for entries
    whose serialized message doesn't even contain the queue name. With a large
    unacked backlog (10k+ entries) this avoids parsing tens of megabytes of
    JSON per call — the dominant memory cost on the monitoring worker.
    """
    tasks: set[str] = set()
    queue_marker = f'"{queue}"'.encode("utf-8")

    for _, v in r.hscan_iter("unacked"):
        v_bytes = cast(bytes, v)
        if queue_marker not in v_bytes:
            continue

        task = json.loads(v_bytes)
        task_description = task[0]
        task_queue = task[2]

        if task_queue != queue:
            continue

        task_id = task_description.get("headers", {}).get("id")
        if not task_id:
            continue

        # if the queue matches and we see the task_id, add it
        tasks.add(task_id)
    return tasks


def celery_get_queue_length(queue: str, r: Redis) -> int:
    """This is a redis specific way to get the length of a celery queue.
    It is priority aware and knows how to count across the multiple redis lists
    used to implement task prioritization.
    This operation is not atomic."""
    total_length = 0
    for i in range(len(OnyxCeleryPriority)):
        queue_name = queue
        if i > 0:
            queue_name += CELERY_SEPARATOR
            queue_name += str(i)

        length = r.llen(queue_name)
        total_length += cast(int, length)

    return total_length


def celery_find_task(task_id: str, queue: str, r: Redis) -> int:
    """This is a redis specific way to find a task for a particular queue in redis.
    It is priority aware and knows how to look through the multiple redis lists
    used to implement task prioritization.
    This operation is not atomic.

    This is a linear search O(n) ... so be careful using it when the task queues can be larger.

    Returns true if the id is in the queue, False if not.
    """
    for priority in range(len(OnyxCeleryPriority)):
        queue_name = f"{queue}{CELERY_SEPARATOR}{priority}" if priority > 0 else queue

        tasks = cast(list[bytes], r.lrange(queue_name, 0, -1))
        for task in tasks:
            task_dict: dict[str, Any] = json.loads(task.decode("utf-8"))
            if task_dict.get("headers", {}).get("id") == task_id:
                return True

    return False


def celery_get_queued_task_ids(queue: str, r: Redis) -> set[str]:
    """This is a redis specific way to build a list of tasks in a queue and return them
    as a set.

    This helps us read the queue once and then efficiently look for missing tasks
    in the queue.
    """

    task_set: set[str] = set()

    for priority in range(len(OnyxCeleryPriority)):
        queue_name = f"{queue}{CELERY_SEPARATOR}{priority}" if priority > 0 else queue

        tasks = cast(list[bytes], r.lrange(queue_name, 0, -1))
        for task in tasks:
            task_dict: dict[str, Any] = json.loads(task.decode("utf-8"))
            task_id = task_dict.get("headers", {}).get("id")
            if task_id:
                task_set.add(task_id)

    return task_set
