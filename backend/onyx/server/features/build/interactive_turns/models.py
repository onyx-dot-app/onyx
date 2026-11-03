from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Literal, Self

from pydantic import BaseModel, ConfigDict

from onyx.server.features.build.interactive_turns.state import InteractiveTurnStatus

if TYPE_CHECKING:
    from onyx.server.features.build.interactive_turns.state import InteractiveTurn


class InteractiveTurnResponse(BaseModel):
    """Interactive turn lifecycle response."""

    turn_id: str
    session_id: str
    status: str
    turn_index: int
    error_detail: str | None = None

    @classmethod
    def from_turn(cls, turn: "InteractiveTurn") -> Self:
        return cls(
            turn_id=str(turn.turn_id),
            session_id=str(turn.session_id),
            status=turn.status,
            turn_index=turn.turn_index,
            error_detail=turn.error_detail,
        )


class InteractiveTurnCompletedPacket(InteractiveTurnResponse):
    """A terminal turn whose transcript and output capture have finished."""

    type: Literal["turn_completed"] = "turn_completed"
    status: Literal["SUCCEEDED", "FAILED", "CANCELLED"]


class PromptOutcome(str, Enum):
    TERMINATED = "terminated"
    TIMED_OUT = "timed_out"
    COMPLETED = "completed"


class PromptResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: PromptOutcome
    final_event_seen: bool = False
    cancelled: bool = False
    terminal_status: InteractiveTurnStatus | None = None
    error_detail: str | None = None
