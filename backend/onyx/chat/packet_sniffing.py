from collections.abc import Sequence

from onyx.server.query_and_chat.streaming_models import Packet


def has_had_message_start(packet_history: Sequence[Packet], current_index: int) -> bool:
    start_ind = len(packet_history) - 1
    for i in range(start_ind, -1, -1):
        if packet_history[i].obj.type == "message_start":
            return False
        elif packet_history[i].ind != current_index:
            return True
    return True
