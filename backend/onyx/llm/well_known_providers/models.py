from pydantic import BaseModel, Field

from onyx.server.manage.llm.models import ModelConfigurationView


class SimpleKnownModel(BaseModel):
    name: str
    display_name: str | None = None


class WellKnownLLMProviderDescriptor(BaseModel):
    name: str

    # NOTE: the recommended visible models are encoded in the known_models list
    known_models: list[ModelConfigurationView] = Field(default_factory=list)
    recommended_default_model: SimpleKnownModel | None = None
