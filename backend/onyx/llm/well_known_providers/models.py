from enum import Enum

from pydantic import BaseModel
from pydantic import Field

from onyx.server.manage.llm.models import ModelConfigurationView


class CustomConfigKeyType(str, Enum):
    # used for configuration values that require manual input
    # i.e., textual API keys (e.g., "abcd1234")
    TEXT_INPUT = "text_input"

    # used for configuration values that require a file to be selected/drag-and-dropped
    # i.e., file based credentials (e.g., "/path/to/credentials/file.json")
    FILE_INPUT = "file_input"

    # used for configuration values that require a selection from predefined options
    SELECT = "select"


class SimpleKnownModel(BaseModel):
    name: str
    display_name: str | None = None


class WellKnownLLMProviderDescriptor(BaseModel):
    name: str

    # NOTE: the recommended visible models are encoded in the known_models list
    known_models: list[ModelConfigurationView] = Field(default_factory=list)
    recommended_default_model: SimpleKnownModel | None = None
