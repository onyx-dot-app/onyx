from uuid import UUID

from pydantic import BaseModel

from onyx.db.models import InputPrompt
from onyx.utils.logger import setup_logger

logger = setup_logger()


class CreateInputPromptRequest(BaseModel):
    prompt: str
    content: str
    is_public: bool


class UpdateInputPromptRequest(BaseModel):
    prompt: str
    content: str
    active: bool


class CreatePersonaInputPromptRequest(BaseModel):
    prompt: str
    content: str
    active: bool = True


class UpdatePersonaInputPromptRequest(BaseModel):
    prompt: str
    content: str
    active: bool


class SyncPersonaInputPromptItem(BaseModel):
    id: int | None = None
    prompt: str
    content: str
    active: bool


class SyncPersonaInputPromptsRequest(BaseModel):
    prompts: list[SyncPersonaInputPromptItem]


class InputPromptResponse(BaseModel):
    id: int
    prompt: str
    content: str
    active: bool


class InputPromptSnapshot(BaseModel):
    id: int
    prompt: str
    content: str
    active: bool
    user_id: UUID | None
    persona_id: int | None
    is_public: bool

    @classmethod
    def from_model(cls, input_prompt: InputPrompt) -> "InputPromptSnapshot":
        return InputPromptSnapshot(
            id=input_prompt.id,
            prompt=input_prompt.prompt,
            content=input_prompt.content,
            active=input_prompt.active,
            user_id=input_prompt.user_id,
            persona_id=input_prompt.persona_id,
            is_public=input_prompt.is_public,
        )
