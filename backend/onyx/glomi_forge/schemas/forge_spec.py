from pydantic import BaseModel
from pydantic import Field


class ForgeSpecInputs(BaseModel):
    uploaded_files: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    external_urls: list[str] = Field(default_factory=list)


class ForgeSpecOutputs(BaseModel):
    primary_format: str = "web"
    extra_formats: list[str] = Field(default_factory=list)


class ForgeSpec(BaseModel):
    title: str
    goal: str
    target_audience: str | None = None
    requirements: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    visual_style: list[str] = Field(default_factory=list)
    inputs: ForgeSpecInputs = Field(default_factory=ForgeSpecInputs)
    outputs: ForgeSpecOutputs = Field(default_factory=ForgeSpecOutputs)
    acceptance_criteria: list[str] = Field(default_factory=list)
