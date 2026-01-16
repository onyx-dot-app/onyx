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


class FileSystemEntry(BaseModel):
    name: str  # File/folder name
    path: str  # Relative path from sandbox root
    is_directory: bool  # True for folders
    size: int | None = None  # File size in bytes
    mime_type: str | None = None  # MIME type for files


class DirectoryListing(BaseModel):
    path: str  # Current directory path
    entries: list[FileSystemEntry]  # Contents
