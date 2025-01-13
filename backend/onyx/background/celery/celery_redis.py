# These are helper objects for tracking the keys we need to write in redis
import json
from typing import Any
from typing import cast

from redis import Redis

from onyx.background.celery.configs.base import CELERY_SEPARATOR
from onyx.configs.constants import OnyxCeleryPriority


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
