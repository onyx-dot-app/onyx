from pydantic import BaseModel
from pydantic import Field


class SandboxFile(BaseModel):
    path: str
    content: str


class CreateSandboxInput(BaseModel):
    session_id: str
    snapshot: str
    env_vars: dict[str, str] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)


class CreateSandboxResult(BaseModel):
    sandbox_id: str
    status: str


class CommandResult(BaseModel):
    exit_code: int
    stdout: str = ""


class PreviewInfo(BaseModel):
    url: str
    port: int
    token: str | None = None
    route: str | None = None


class SandboxStatusInfo(BaseModel):
    sandbox_id: str
    state: str
