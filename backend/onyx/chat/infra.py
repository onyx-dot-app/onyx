from collections.abc import Callable
from collections.abc import Generator
from queue import Empty
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
        # TODO this can be removed, nothing should need to use this
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


def run_with_emitter_wrapper(
    func: Callable[..., None],
    emitter: Emitter,
    is_connected: Callable[[], bool],
    *args: Any,
    **kwargs: Any,
) -> Generator[Packet, None]:
    """
    Explicit wrapper function that runs a function in a background thread
    with event streaming capabilities.

    The wrapped function should accept emitter as first arg and use it to emit
    Packet objects. This wrapper polls every 300ms to check if stop signal is set.

    Args:
        func: The function to wrap (should accept emitter as first arg)
        emitter: Emitter instance for sending packets
        is_connected: Callable that returns False when stop signal is set
        *args: Additional positional arguments for func
        **kwargs: Additional keyword arguments for func

    Usage:
        packets = run_with_emitter_wrapper(
            my_func,
            emitter=emitter,
            is_connected=check_func,
            arg1, arg2, kwarg1=value1
        )
        for packet in packets:
            # Process packets
            pass
    """

    def run_with_exception_capture() -> None:
        try:
            func(emitter, *args, **kwargs)
        except Exception as e:
            # If execution fails, emit an exception packet
            emitter.emit(
                Packet(
                    turn_index=0,
                    obj=PacketException(type="error", exception=e),
                )
            )

    # Run the function in a background thread
    thread = run_in_background(run_with_exception_capture)

    try:
        while True:
            # Poll queue with 300ms timeout for natural stop signal checking
            try:
                pkt: Packet = emitter.bus.get(timeout=0.3)
            except Empty:
                # Timeout - check stop signal and continue
                if not is_connected():
                    # Stop signal detected, kill the thread
                    break
                continue

            # Handle received packet
            if pkt.obj == OverallStop(type="stop"):
                yield pkt
                break
            elif isinstance(pkt.obj, PacketException):
                raise pkt.obj.exception
            else:
                yield pkt

            # Also check stop signal after yielding each packet
            if not is_connected():
                break
    finally:
        # Only wait for thread if it wasn't stopped by user
        if is_connected():
            wait_on_background(thread)
        # If stopped by user, we just let the thread die without waiting


def emitter_generator_wrapper(
    wrapped_func: Callable[..., None],
) -> Callable[..., Generator[Packet, None]]:
    """
    DEPRECATED: Use run_with_emitter_wrapper instead for explicit control.

    Legacy decorator that wraps a function to provide event streaming capabilities.
    Kept for backward compatibility with existing code.
    """

    def wrapper(emitter: Emitter, *args: Any, **kwargs: Any) -> Generator[Packet, None]:
        def run_with_exception_capture() -> None:
            try:
                wrapped_func(emitter, *args, **kwargs)
            except Exception as e:
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
