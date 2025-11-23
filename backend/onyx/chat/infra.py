from collections.abc import Callable
from collections.abc import Generator
from queue import Queue
from typing import Any

from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import PacketException
from onyx.utils.threadpool_concurrency import run_in_background
from onyx.utils.threadpool_concurrency import wait_on_background


class Emitter:
    """Use this inside tools to emit arbitrary UI progress."""

    def __init__(self, bus: Queue):
        self.bus = bus
        self.packet_history: list[Packet] = []

    def emit(self, packet: Packet) -> None:
        # NOTE: when passing emitters in for multi-threading, the order may be non-deterministic
        # however it is safe at least for now from data issues due to the CPython GIL
        # still, probably try not to use the packet history in multi-threaded contexts
        self.bus.put(packet)  # ✅ Thread-safe
        self.packet_history.append(packet)  # ❌ NOT thread-safe technically


def get_default_emitter() -> Emitter:
    bus: Queue[Packet] = Queue()
    emitter = Emitter(bus)
    return emitter


def emitter_generator_wrapper(
    wrapped_func: Callable[..., None],
) -> Callable[..., Generator[Packet, None]]:
    """
    Decorator that wraps a function to provide event streaming capabilities.

    The wrapped function should accept any arguments and use an Emitter to emit
    Packet objects. The decorator converts the function into a generator that
    yields Packets from the emitter's bus.

    Usage:
    @emitter_generator_wrapper
    def my_func(emitter, *args, **kwargs):
        # Your logic here - use emitter.emit() to send packets
        emitter.emit(Packet(ind=0, obj=SomeEvent(...)))
        pass

    Then call it like:
    generator = my_func(emitter, *args, **kwargs)
    for packet in generator:
        # Process packets
        pass
    """

    def wrapper(emitter: Emitter, *args: Any, **kwargs: Any) -> Generator[Packet, None]:
        def run_with_exception_capture() -> None:
            try:
                wrapped_func(emitter, *args, **kwargs)
            except Exception as e:
                # Ok if we don't know the actual turn or tab, if it's failed at this level
                # the entire flow is dead
                emitter.emit(
                    Packet(
                        turn_index=0,
                        obj=PacketException(type="error", exception=e),
                    )
                )

        thread = run_in_background(run_with_exception_capture)
        while True:
            pkt: Packet = emitter.bus.get()
            if pkt.obj == OverallStop(type="stop"):
                yield pkt
                break
            elif isinstance(pkt.obj, PacketException):
                raise pkt.obj.exception
            else:
                yield pkt
        wait_on_background(thread)

    return wrapper
