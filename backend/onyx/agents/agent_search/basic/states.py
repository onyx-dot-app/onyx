from typing import TypedDict

from onyx.chat.llm_response_handler import LLMResponseHandlerManager
from onyx.chat.prompt_builder.answer_prompt_builder import LLMCall

## Update States


## Graph Input State


class BasicInput(TypedDict):
    base_question: str
    last_llm_call: LLMCall | None
    response_handler_manager: LLMResponseHandlerManager
    calls: int


## Graph Output State


class BasicOutput(TypedDict):
    pass


class BasicStateUpdate(TypedDict):
    last_llm_call: LLMCall | None
    calls: int


## Graph State


class BasicState(
    BasicInput,
    BasicOutput,
):
    pass
