"""Execution scopes for model generation.

Cancellation of in-flight provider calls is not implemented yet; it will live
in this module. The context isolation below already exists because streaming
needs it: a stream's tracing span must not leak into the caller's context, and
cancellation will add a per-generation signal that needs the same isolation.
"""

from collections.abc import Callable, Generator
from contextvars import copy_context
from functools import wraps
from typing import ParamSpec, TypeVar

_P = ParamSpec("_P")
_T = TypeVar("_T")


def isolated_context(
    generate: Callable[_P, Generator[_T, None, None]],
) -> Callable[_P, Generator[_T, None, None]]:
    """Run a generator in its own context copy, across next and close.

    A generator shares its caller's context, so a span opened inside it would
    stay current for the caller between yields and after an early close.
    """

    @wraps(generate)
    def start(*args: _P.args, **kwargs: _P.kwargs) -> Generator[_T, None, None]:
        execution = copy_context()
        source = execution.run(generate, *args, **kwargs)

        def iterate() -> Generator[_T, None, None]:
            try:
                while True:
                    try:
                        value = execution.run(source.__next__)
                    except StopIteration:
                        return
                    yield value
            finally:
                execution.run(source.close)

        return iterate()

    return start
