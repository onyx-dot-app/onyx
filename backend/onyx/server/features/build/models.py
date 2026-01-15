from pydantic import BaseModel


class CreateSessionRequest(BaseModel):
    task: str
    available_sources: list[str] | None = None


class CreateSessionResponse(BaseModel):
    session_id: str


class ExecuteRequest(BaseModel):
    task: str
    context: str | None = None


class ArtifactInfo(BaseModel):
    artifact_type: str  # "webapp", "file", "markdown", "image"
    path: str
    filename: str
    mime_type: str | None = None


class SessionStatus(BaseModel):
    session_id: str
    status: str  # "idle", "running", "completed", "failed"
    webapp_url: str | None = None
