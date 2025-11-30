from queue import Queue

from onyx.server.query_and_chat.streaming_models import Packet


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
