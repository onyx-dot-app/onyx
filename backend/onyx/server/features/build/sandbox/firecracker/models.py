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


class SessionInstanceTable(BaseModel):
    # Chat session ID → (attempt, generation) of the VM instance it is set
    # up on (directory made, last save restored).
    sessions: dict[str, tuple[int, int]] = {}


class SessionSave(BaseModel):
    """The committed save of one chat session's directory."""

    model_config = ConfigDict(frozen=True)

    # None: the session had nothing to save.
    file_id: str | None
    size_bytes: int
    sha256: str
    # Top-level directories in the archive (what a restore replaces).
    roots: list[str]
    saved_at: float


class IdSet(BaseModel):
    """A set of IDs kept in one cache record (saved sessions, artifacts)."""

    ids: list[str] = []
