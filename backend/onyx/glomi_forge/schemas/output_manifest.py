from pydantic import BaseModel
from pydantic import Field


class PreviewEntry(BaseModel):
    url: str
    port: int
    route: str | None = None


class OutputFile(BaseModel):
    path: str
    kind: str
    size_bytes: int | None = None


class OutputManifest(BaseModel):
    artifact_version: int = 1
    primary_artifact_path: str
    primary_artifact_type: str
    preview_entry: PreviewEntry | None = None
    files: list[OutputFile] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
