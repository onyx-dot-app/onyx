from collections.abc import Callable
from collections.abc import Generator
from typing import Any
from typing import Dict
from typing import List

from onyx.chat.turn.models import ChatTurnDependencies
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import PacketException
from onyx.utils.threadpool_concurrency import run_in_background
from onyx.utils.threadpool_concurrency import wait_on_background


def unified_event_stream(
    turn_func: Callable[..., None],
) -> Callable[..., Generator[Packet, None]]:
    """
    Decorator that wraps a turn_func to provide event streaming capabilities.

    Usage:
    @unified_event_stream
    def my_turn_func(messages, dependencies, *args, **kwargs):
        # Your turn logic here
        pass

    Then call it like:
    generator = my_turn_func(messages, dependencies, *args, **kwargs)
    """

    def wrapper(
        messages: List[Dict[str, Any]],
        dependencies: ChatTurnDependencies,
        *args: Any,
        **kwargs: Any
    ) -> Generator[Packet, None]:
        def run_with_exception_capture() -> None:
            try:
                turn_func(messages, dependencies, *args, **kwargs)
            except Exception as e:
                dependencies.emitter.emit(
                    Packet(ind=0, obj=PacketException(type="error", exception=e))
                )

        thread = run_in_background(run_with_exception_capture)
        while True:
            pkt: Packet = dependencies.emitter.bus.get()
            if pkt.obj == OverallStop(type="stop"):
                yield pkt
                break
            elif isinstance(pkt.obj, PacketException):
                raise pkt.obj.exception
            else:
                yield pkt
        wait_on_background(thread)

    return wrapper
