from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from onyx.server.features.build.interactive_turns.state import InteractiveTurn


class InteractiveTurnResponse(BaseModel):
    """Interactive turn lifecycle response."""

    turn_id: str
    session_id: str
    status: str
    turn_index: int

    @classmethod
    def from_turn(cls, turn: "InteractiveTurn") -> "InteractiveTurnResponse":
        return cls(
            turn_id=str(turn.turn_id),
            session_id=str(turn.session_id),
            status=turn.status,
            turn_index=turn.turn_index,
        )


class InteractiveTurnStartResponse(InteractiveTurnResponse):
    """Turn response with the runtime state used to start it."""

    skills_stale: bool

    @classmethod
    def from_turn_and_skills_state(
        cls,
        turn: "InteractiveTurn",
        *,
        skills_stale: bool,
    ) -> "InteractiveTurnStartResponse":
        return cls(
            turn_id=str(turn.turn_id),
            session_id=str(turn.session_id),
            status=turn.status,
            turn_index=turn.turn_index,
            skills_stale=skills_stale,
        )
