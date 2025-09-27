import contextvars
import threading
from collections.abc import Callable
from collections.abc import Generator
from queue import Queue
from typing import Any
from typing import Dict
from typing import List

from onyx.chat.turn.infra.chat_turn_event_stream import Emitter
from onyx.chat.turn.models import RunDependencies
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet


def unified_event_stream(
    turn_func: Callable[[List[Dict[str, Any]], RunDependencies], None],
) -> Callable[[List[Dict[str, Any]], RunDependencies], Generator[Packet, None]]:
    """
    Decorator that wraps a turn_func to provide event streaming capabilities.

    Usage:
    @unified_event_stream
    def my_turn_func(messages, dependencies):
        # Your turn logic here
        pass

    # Then call it like:
    # generator = my_turn_func(messages, dependencies)
    """

    def wrapper(
        messages: List[Dict[str, Any]], dependencies: RunDependencies
    ) -> Generator[Packet, None]:
        bus: Queue = Queue()
        emitter = Emitter(bus)
        current_context = contextvars.copy_context()
        dependencies.emitter = emitter
        t = threading.Thread(
            target=current_context.run,
            args=(
                turn_func,
                messages,
                dependencies,
            ),
            daemon=True,
        )
        t.start()
        while True:
            pkt: Packet = emitter.bus.get()
            print("packet", pkt)
            if pkt.obj == OverallStop(type="stop"):
                yield pkt
                break
            else:
                yield pkt

    return wrapper
