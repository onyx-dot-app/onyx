from pydantic import BaseModel


class Placement(BaseModel):
    # Which iterative block in the UI is this part of, these are ordered and smaller ones happened first
    turn_index: int
    # For parallel tool calls to preserve order of execution
    tab_index: int = 0
    # Used for tools/agents that call other tools, this currently doesn't support nested agents but can be added later
    sub_turn_index: int | None = None
