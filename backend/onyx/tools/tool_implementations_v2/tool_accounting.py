import functools
import inspect
from collections.abc import Callable
from typing import Any
from typing import cast
from typing import TypeVar

from agents import RunContextWrapper

from onyx.chat.turn.models import ChatTurnContext
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SectionEnd

F = TypeVar("F", bound=Callable)


def tool_accounting(func: F) -> F:
    """
    Decorator that adds tool accounting functionality to tool functions.
    Handles both sync and async functions automatically.

    This decorator:
    1. Increments the current_run_step index at the beginning
    2. Emits a section end packet and increments current_run_step at the end
    3. Ensures the cleanup happens even if an exception occurs

    Args:
        func: The function to decorate. Must take a RunContextWrapper[ChatTurnContext] as first argument.

    Returns:
        The decorated function with tool accounting functionality.
    """

    @functools.wraps(func)
    def wrapper(
        run_context: RunContextWrapper[ChatTurnContext], *args: Any, **kwargs: Any
    ) -> Any:
        # Increment current_run_step at the beginning
        run_context.context.current_run_step += 1

        try:
            # Call the original function
            result = func(run_context, *args, **kwargs)

            # If it's a coroutine, we need to handle it differently
            if inspect.iscoroutine(result):
                # For async functions, we need to return a coroutine that handles the cleanup
                async def async_wrapper() -> Any:
                    try:
                        return await result
                    finally:
                        _emit_section_end(run_context)

                return async_wrapper()
            else:
                # For sync functions, emit cleanup immediately
                _emit_section_end(run_context)
                return result

        except Exception:
            # Always emit cleanup even if an exception occurred
            _emit_section_end(run_context)
            raise

    return cast(F, wrapper)


def _emit_section_end(run_context: RunContextWrapper[ChatTurnContext]) -> None:
    """Helper function to emit section end packet and increment current_run_step."""
    index = run_context.context.current_run_step
    run_context.context.run_dependencies.emitter.emit(
        Packet(
            ind=index,
            obj=SectionEnd(
                type="section_end",
            ),
        )
    )
    run_context.context.current_run_step += 1
