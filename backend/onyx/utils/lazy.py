from collections.abc import Callable
from functools import lru_cache
from typing import TypeVar

R = TypeVar("R")


def lazy_eval(func: Callable[[], R]) -> Callable[[], R]:
    @lru_cache(maxsize=1)
    def lazy_func() -> R:
        return func()

    return lazy_func
