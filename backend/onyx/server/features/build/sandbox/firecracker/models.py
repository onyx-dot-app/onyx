"""Pydantic models of the Firecracker harness sandbox state."""

from pydantic import BaseModel, ConfigDict


class ExecSessionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    exec_session_id: str
    chat_session_id: str
    execution_id: str
    attempt: int
    generation: int
    stdout_offset: int = 0
    stderr_offset: int = 0
    last_used: float

    def on_instance(self, attempt: int, generation: int) -> bool:
        return (self.attempt, self.generation) == (attempt, generation)


class ExecSessionTable(BaseModel):
    sessions: dict[str, ExecSessionRecord] = {}


class HarnessActivity(BaseModel):
    # chat session ID → Unix seconds when the mark expires.
    turns: dict[str, float] = {}
    approvals: dict[str, float] = {}


class ManagedImageRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    attempt: int
    generation: int
    image_id: str
