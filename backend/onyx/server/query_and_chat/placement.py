from pydantic import BaseModel


class Placement(BaseModel):
    """Coordinates that identify where a streaming packet belongs in the UI.

    The frontend uses these fields to route each packet to the correct turn,
    tool tab, agent sub-turn, and (in multi-model mode) response column.

    Attributes:
        turn_index: Monotonically increasing index of the iterative reasoning block
            (e.g. tool call round) within this chat message. Lower values happened first.
        tab_index: Disambiguates parallel tool calls within the same turn so each
            tool's output can be displayed in its own tab.
        sub_turn_index: Nesting level for tools that invoke other tools. ``None`` for
            top-level packets; an integer for tool-within-tool output.
        model_index: Which model this packet belongs to. ``0`` for single-model
            responses; ``0``, ``1``, or ``2`` for multi-model comparison. ``None``
            for pre-LLM setup packets (e.g. message ID info) that are yielded
            before any Emitter runs.
    """

    turn_index: int
    tab_index: int = 0
    sub_turn_index: int | None = None
    model_index: int | None = None
