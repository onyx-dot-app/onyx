from queue import Queue

from onyx.server.query_and_chat.streaming_models import Packet


class Emitter:
    """Use this inside tools to emit arbitrary UI progress."""

    def __init__(self, bus: Queue):
        self.bus = bus

    def emit(self, packet: Packet) -> None:
        self.bus.put(packet)  # Thread-safe


def get_default_emitter() -> Emitter:
    bus: Queue[Packet] = Queue()
    emitter = Emitter(bus)
    return emitter
