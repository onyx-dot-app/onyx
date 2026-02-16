import time

from redis.lock import Lock as RedisLock


def extend_lock(lock: RedisLock, timeout: int, last_lock_time: float) -> float:
    current_time = time.monotonic()
    if current_time - last_lock_time >= (timeout / 4):
        lock.reacquire()
        last_lock_time = current_time

    return last_lock_time
