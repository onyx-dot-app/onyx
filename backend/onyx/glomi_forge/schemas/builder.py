from pydantic import BaseModel
from pydantic import Field


class BuilderConfig(BaseModel):
    model: str | None = None
    timeout_seconds: int | None = None


class StartBuildInput(BaseModel):
    build_session_id: str
    sandbox_id: str
    mode: str = "initial_build"
    instruction: str = ""
    builder_config: BuilderConfig = Field(default_factory=BuilderConfig)


class StartBuildResult(BaseModel):
    builder_session_id: str
