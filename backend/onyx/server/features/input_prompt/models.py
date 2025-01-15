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
    is_public: bool

    @classmethod
    def from_model(cls, input_prompt: InputPrompt) -> "InputPromptSnapshot":
        return InputPromptSnapshot(
            id=input_prompt.id,
            prompt=input_prompt.prompt,
            content=input_prompt.content,
            active=input_prompt.active,
            user_id=input_prompt.user_id,
            is_public=input_prompt.is_public,
        )
