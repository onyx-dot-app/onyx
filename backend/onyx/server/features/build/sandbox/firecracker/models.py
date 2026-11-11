"""Pydantic models of the Firecracker harness sandbox state."""

from pydantic import BaseModel, ConfigDict


class ExecSessionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    exec_session_id: str
    chat_session_id: str
    execution_id: str
    # The VM instance that runs the command.
    attempt: int
    generation: int
    stdout_offset: int = 0
    stderr_offset: int = 0
    last_used: float


class ExecSessionTable(BaseModel):
    sessions: dict[str, ExecSessionRecord] = {}


class HarnessActivity(BaseModel):
    # Mark name ("turn:<chat session>", "approval:<chat session>") → Unix
    # seconds when it expires.
    marks: dict[str, float] = {}
