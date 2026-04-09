from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Callable,
    Coroutine,
    Generator,
)
from typing import TypeVar

RETURN_TYPE = TypeVar("RETURN_TYPE")

DependencyCallable = Callable[
    ...,
    RETURN_TYPE
    | Coroutine[None, None, RETURN_TYPE]
    | AsyncGenerator[RETURN_TYPE, None]
    | Generator[RETURN_TYPE, None, None]
    | AsyncIterator[RETURN_TYPE],
]
