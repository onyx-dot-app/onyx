# These are helper objects for tracking the keys we need to write in redis
from typing import cast

from redis import Redis

from danswer.background.celery.configs.base import CELERY_SEPARATOR
from danswer.configs.constants import DanswerCeleryPriority


def celery_get_queue_length(queue: str, r: Redis) -> int:
    """This is a redis specific way to get the length of a celery queue.
    It is priority aware and knows how to count across the multiple redis lists
    used to implement task prioritization.
    This operation is not atomic."""
    total_length = 0
    for i in range(len(DanswerCeleryPriority)):
        queue_name = queue
        if i > 0:
            queue_name += CELERY_SEPARATOR
            queue_name += str(i)

        length = r.llen(queue_name)
        total_length += cast(int, length)

    return total_length
