# These are helper objects for tracking the keys we need to write in redis
import json
from typing import Any
from typing import cast

from celery import Celery
from redis import Redis

from onyx.background.celery.configs.base import CELERY_SEPARATOR
from onyx.configs.constants import OnyxCeleryPriority


def celery_get_unacked_length(r: Redis) -> int:
    """Checking the unacked queue is useful because a non-zero length tells us there
    may be prefetched tasks.

    There can be other tasks in here besides indexing tasks, so this is mostly useful
    just to see if the task count is non zero.

    ref: https://blog.hikaru.run/2022/08/29/get-waiting-tasks-count-in-celery.html
    """
    length = cast(int, r.hlen("unacked"))
    return length


def celery_get_unacked_task_ids(queue: str, r: Redis) -> set[str]:
    """Gets the set of task id's matching the given queue in the unacked hash.

    Unacked entries belonging to the indexing queues are "prefetched", so this gives
    us crucial visibility as to what tasks are in that state.
    """
    tasks: set[str] = set()

    for _, v in r.hscan_iter("unacked"):
        v_bytes = cast(bytes, v)
        v_str = v_bytes.decode("utf-8")
        task = json.loads(v_str)

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


def celery_inspect_get_workers(name_filter: str | None, app: Celery) -> list[str]:
    """Returns a list of current workers containing name_filter, or all workers if
    name_filter is None.

    We've empirically discovered that the celery inspect API is potentially unstable
    and may hang or return empty results when celery is under load. Suggest using this
    more to debug and troubleshoot than in production code.
    """
    worker_names: list[str] = []

    # filter for and create an indexing specific inspect object
    inspect = app.control.inspect()
    workers: dict[str, Any] = inspect.ping()  # type: ignore
    if workers:
        for worker_name in list(workers.keys()):
            # if the name filter not set, return all worker names
            if not name_filter:
                worker_names.append(worker_name)
                continue

            # if the name filter is set, return only worker names that contain the name filter
            if name_filter not in worker_name:
                continue

            worker_names.append(worker_name)

    return worker_names


def celery_inspect_get_reserved(worker_names: list[str], app: Celery) -> set[str]:
    """Returns a list of reserved tasks on the specified workers.

    We've empirically discovered that the celery inspect API is potentially unstable
    and may hang or return empty results when celery is under load. Suggest using this
    more to debug and troubleshoot than in production code.
    """
    reserved_task_ids: set[str] = set()

    inspect = app.control.inspect(destination=worker_names)

    # get the list of reserved tasks
    reserved_tasks: dict[str, list] | None = inspect.reserved()  # type: ignore
    if reserved_tasks:
        for _, task_list in reserved_tasks.items():
            for task in task_list:
                reserved_task_ids.add(task["id"])

    return reserved_task_ids


def celery_inspect_get_active(worker_names: list[str], app: Celery) -> set[str]:
    """Returns a list of active tasks on the specified workers.

    We've empirically discovered that the celery inspect API is potentially unstable
    and may hang or return empty results when celery is under load. Suggest using this
    more to debug and troubleshoot than in production code.
    """
    active_task_ids: set[str] = set()

    inspect = app.control.inspect(destination=worker_names)

    # get the list of reserved tasks
    active_tasks: dict[str, list] | None = inspect.active()  # type: ignore
    if active_tasks:
        for _, task_list in active_tasks.items():
            for task in task_list:
                active_task_ids.add(task["id"])

    return active_task_ids
